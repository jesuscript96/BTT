// Core types for the AssistantBus — see docs/assistant/arquitectura.md

/** Minimal JSON Schema subset supported by validate.ts and function calling. */
export interface JSONSchema {
    type?: 'object' | 'array' | 'string' | 'number' | 'integer' | 'boolean' | 'null';
    description?: string;
    properties?: Record<string, JSONSchema>;
    required?: string[];
    items?: JSONSchema;
    enum?: (string | number)[];
    minimum?: number;
    maximum?: number;
    pattern?: string;
    additionalProperties?: boolean | JSONSchema;
}

/**
 * auto    → runs immediately
 * confirm → chat shows a preview card; user must approve
 * danger  → like confirm but for destructive actions (deletes)
 */
export type ConfirmLevel = 'auto' | 'confirm' | 'danger';

export interface ActionResult {
    ok: boolean;
    /** Echo of what was applied, or any payload useful to the LLM. */
    result?: unknown;
    error?: string;
}

export interface AssistantActionDef {
    /** Dot-namespaced unique name, e.g. "backtest.fill_form". */
    name: string;
    /** Spanish description shown to the LLM — be specific about effects. */
    description: string;
    /** JSON Schema for the arguments (drives function calling + validation). */
    parameters: JSONSchema;
    confirm?: ConfirmLevel;
    handler: (args: Record<string, unknown>) => ActionResult | Promise<ActionResult>;
}

/** OpenAI-format tool definition sent to the LLM. */
export interface ToolDef {
    type: 'function';
    function: {
        name: string;
        description: string;
        parameters: JSONSchema;
    };
}

export interface ToolCall {
    id: string;
    name: string;
    arguments: Record<string, unknown>;
    rawArguments: string;
}

export type ContextGetter = () => unknown;
