// React bindings for the AssistantBus.
//
// useAssistantAction  — register a capability while the component is mounted.
// useAssistantContext — publish live state the assistant can read each turn.
//
// Both keep the latest handler/getter in a ref so registration happens once
// per mount but always sees fresh component state.

"use client";

import { useEffect, useRef } from 'react';
import { assistantBus } from './bus';
import type { ActionResult, AssistantActionDef, ContextGetter } from './types';

export function useAssistantAction(def: AssistantActionDef): void {
    const handlerRef = useRef(def.handler);
    handlerRef.current = def.handler;

    const { name, description, parameters, confirm } = def;

    useEffect(() => {
        const unregister = assistantBus.registerAction({
            name,
            description,
            parameters,
            confirm,
            handler: (args): ActionResult | Promise<ActionResult> => handlerRef.current(args),
        });
        return unregister;
        // Re-register only if identity fields change; parameters are assumed
        // stable per mount (declare them outside render or memoized).
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [name]);
}

export function useAssistantContext(key: string, getter: ContextGetter): void {
    const getterRef = useRef(getter);
    getterRef.current = getter;

    useEffect(() => {
        const unregister = assistantBus.registerContext(key, () => getterRef.current());
        return unregister;
    }, [key]);
}
