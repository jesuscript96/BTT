// HTTP client for the backend AI Gateway (/api/assistant/chat).
//
// The provider API key lives on the server. As a transitional fallback the
// key the user saved in localStorage (legacy direct-DeepSeek setup) is sent
// in a header, which the gateway only uses when no server key is configured.

import type { JSONSchema, ToolCall, ToolDef } from './types';

const RAW_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8010/api';
const API_BASE = (() => {
    const trimmed = RAW_BASE.replace(/\/+$/, '');
    return trimmed.endsWith('/api') ? trimmed : `${trimmed}/api`;
})();

export interface ChatApiMessage {
    role: 'system' | 'user' | 'assistant' | 'tool';
    content: string | null;
    tool_calls?: {
        id: string;
        type: 'function';
        function: { name: string; arguments: string };
    }[];
    tool_call_id?: string;
}

export interface AssistantChatParams {
    messages: ChatApiMessage[];
    tools?: ToolDef[];
    temperature?: number;
    page?: string;
    signal?: AbortSignal;
}

export interface AssistantChatResult {
    content: string;
    toolCalls: ToolCall[];
}

function buildHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (typeof window !== 'undefined') {
        const legacyKey = localStorage.getItem('DEEPSEEK_API_KEY');
        if (legacyKey) headers['X-Assistant-Key'] = legacyKey;
    }
    return headers;
}

interface ToolCallAccumulator {
    id: string;
    name: string;
    arguments: string;
}

function parseAccumulatedToolCalls(acc: Map<number, ToolCallAccumulator>): ToolCall[] {
    return [...acc.entries()]
        .sort(([a], [b]) => a - b)
        .map(([, tc]) => {
            let parsed: Record<string, unknown> = {};
            try {
                parsed = tc.arguments ? JSON.parse(tc.arguments) : {};
            } catch {
                // leave rawArguments for the caller to surface to the LLM
            }
            return { id: tc.id, name: tc.name, arguments: parsed, rawArguments: tc.arguments };
        });
}

/**
 * Streaming chat via SSE. onDelta fires with the text accumulated so far.
 * Resolves with the final content and any tool calls the model requested.
 */
export async function assistantChatStream(
    params: AssistantChatParams,
    onDelta?: (textSoFar: string) => void
): Promise<AssistantChatResult> {
    const response = await fetch(`${API_BASE}/assistant/chat`, {
        method: 'POST',
        headers: buildHeaders(),
        signal: params.signal,
        body: JSON.stringify({
            messages: params.messages,
            tools: params.tools && params.tools.length > 0 ? params.tools : undefined,
            temperature: params.temperature ?? 0.2,
            stream: true,
            page: params.page,
        }),
    });

    if (!response.ok || !response.body) {
        const errBody = await response.json().catch(() => ({} as { detail?: string }));
        throw new Error(errBody.detail || `HTTP ${response.status} del gateway del asistente`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let content = '';
    const toolAcc = new Map<number, ToolCallAccumulator>();

    const processLine = (line: string) => {
        if (!line.startsWith('data:')) return;
        const data = line.slice(5).trim();
        if (!data || data === '[DONE]') return;
        let chunk: any;
        try {
            chunk = JSON.parse(data);
        } catch {
            return;
        }
        if (chunk.error) {
            throw new Error(chunk.error.message || 'Error del proveedor LLM');
        }
        const delta = chunk.choices?.[0]?.delta;
        if (!delta) return;
        if (typeof delta.content === 'string' && delta.content.length > 0) {
            content += delta.content;
            onDelta?.(content);
        }
        for (const tcDelta of delta.tool_calls ?? []) {
            const idx = tcDelta.index ?? 0;
            const existing = toolAcc.get(idx) ?? { id: '', name: '', arguments: '' };
            if (tcDelta.id) existing.id = tcDelta.id;
            if (tcDelta.function?.name) existing.name += tcDelta.function.name;
            if (tcDelta.function?.arguments) existing.arguments += tcDelta.function.arguments;
            toolAcc.set(idx, existing);
        }
    };

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) processLine(line.trim());
    }
    if (buffer.trim()) processLine(buffer.trim());

    return { content, toolCalls: parseAccumulatedToolCalls(toolAcc) };
}

/** Non-streaming chat (used by the Ticker Analysis auto-report). */
export async function assistantChatOnce(params: AssistantChatParams): Promise<string> {
    const response = await fetch(`${API_BASE}/assistant/chat`, {
        method: 'POST',
        headers: buildHeaders(),
        signal: params.signal,
        body: JSON.stringify({
            messages: params.messages,
            temperature: params.temperature ?? 0.1,
            stream: false,
            page: params.page,
        }),
    });
    if (!response.ok) {
        const errBody = await response.json().catch(() => ({} as { detail?: string }));
        const detail = errBody.detail || `HTTP ${response.status}`;
        const err = new Error(detail);
        if (response.status === 503 && String(detail).startsWith('NO_KEY')) err.name = 'NoKeyError';
        throw err;
    }
    const data = await response.json();
    return data.choices?.[0]?.message?.content ?? '';
}

export type { ToolDef, JSONSchema };
