// AssistantBus — central registry of actions and context providers.
//
// Components declare what they can do (registerAction) and what they know
// (registerContext) while mounted. The ChatBot discovers both dynamically:
// the action manifest becomes the LLM's function-calling tools, and the
// context snapshot is injected into the system prompt each turn.
//
// execute() validates arguments against the action's JSON Schema before
// touching any handler, and waits briefly for actions that are about to
// mount (navigate-then-act flows). See docs/assistant/arquitectura.md.

import type { ActionResult, AssistantActionDef, ContextGetter, ToolDef } from './types';
import { formatErrors, validateAgainstSchema } from './validate';

type Listener = () => void;

const ACTION_MOUNT_TIMEOUT_MS = 4000;

/**
 * LLM providers restrict tool names to [a-zA-Z0-9_-], so the dot-namespaced
 * canonical names ("backtest.fill_form") travel over the wire with dots
 * replaced by underscores. The bus keeps a reverse map to resolve calls.
 */
const toWireName = (name: string) => name.replace(/\./g, '_');

class AssistantBus {
    private actions = new Map<string, AssistantActionDef>();
    private wireToCanonical = new Map<string, string>();
    private contexts = new Map<string, ContextGetter>();
    private listeners = new Set<Listener>();

    // ── Registration ─────────────────────────────────────────────

    registerAction(def: AssistantActionDef): () => void {
        this.actions.set(def.name, def);
        this.wireToCanonical.set(toWireName(def.name), def.name);
        this.notify();
        return () => {
            // Only unregister if this exact def is still the registered one
            // (a remount may have replaced it already).
            if (this.actions.get(def.name) === def) {
                this.actions.delete(def.name);
                this.wireToCanonical.delete(toWireName(def.name));
                this.notify();
            }
        };
    }

    registerContext(key: string, getter: ContextGetter): () => void {
        this.contexts.set(key, getter);
        this.notify();
        return () => {
            if (this.contexts.get(key) === getter) {
                this.contexts.delete(key);
                this.notify();
            }
        };
    }

    subscribe(listener: Listener): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    private notify() {
        this.listeners.forEach(l => l());
    }

    // ── Discovery ────────────────────────────────────────────────

    /** Resolves canonical ("backtest.fill_form") or wire ("backtest_fill_form") names. */
    getAction(name: string): AssistantActionDef | undefined {
        return this.actions.get(name) ?? this.actions.get(this.wireToCanonical.get(name) ?? '');
    }

    listActions(): AssistantActionDef[] {
        return [...this.actions.values()];
    }

    /** OpenAI-format tools manifest for the LLM (only what's mounted now). */
    getToolsManifest(): ToolDef[] {
        return this.listActions().map(a => ({
            type: 'function',
            function: { name: toWireName(a.name), description: a.description, parameters: a.parameters },
        }));
    }

    /** Snapshot of every published context, keyed by provider. */
    getContextSnapshot(): Record<string, unknown> {
        const snapshot: Record<string, unknown> = {};
        for (const [key, getter] of this.contexts) {
            try {
                snapshot[key] = getter();
            } catch (e) {
                snapshot[key] = { error: `context getter falló: ${String(e)}` };
            }
        }
        return snapshot;
    }

    // ── Execution ────────────────────────────────────────────────

    /**
     * Validate and run an action. If the action isn't registered yet (e.g.
     * the LLM navigated and the target page is still mounting), wait up to
     * ACTION_MOUNT_TIMEOUT_MS for it to appear before failing.
     */
    async execute(name: string, args: Record<string, unknown>): Promise<ActionResult> {
        const action = this.getAction(name) ?? (await this.waitForAction(name));
        if (!action) {
            // List wire names: that's what the LLM must use in tool calls.
            const available = this.listActions().map(a => toWireName(a.name)).join(', ') || '(ninguna)';
            return {
                ok: false,
                error:
                    `La acción "${name}" no está disponible en la página actual. ` +
                    `Acciones disponibles ahora: ${available}. ` +
                    `Usa app_navigate para ir a la página adecuada primero.`,
            };
        }

        const errors = validateAgainstSchema(args ?? {}, action.parameters);
        if (errors.length > 0) {
            return { ok: false, error: `Parámetros inválidos — ${formatErrors(errors)}` };
        }

        try {
            return await action.handler(args ?? {});
        } catch (e) {
            return { ok: false, error: `La acción lanzó un error: ${String(e)}` };
        }
    }

    private waitForAction(name: string): Promise<AssistantActionDef | undefined> {
        return new Promise(resolve => {
            const timer = setTimeout(() => {
                unsubscribe();
                resolve(undefined);
            }, ACTION_MOUNT_TIMEOUT_MS);
            const unsubscribe = this.subscribe(() => {
                const found = this.getAction(name);
                if (found) {
                    clearTimeout(timer);
                    unsubscribe();
                    resolve(found);
                }
            });
        });
    }
}

/** Singleton — survives page navigation within the SPA. */
export const assistantBus = new AssistantBus();
