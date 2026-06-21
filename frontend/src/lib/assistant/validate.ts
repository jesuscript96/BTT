// Lightweight JSON Schema validator for assistant tool arguments.
// Covers the subset declared in types.ts (objects, arrays, enums, ranges).
// Intentionally dependency-free; swap for zod/ajv if the schemas outgrow it.

import type { JSONSchema } from './types';

export interface ValidationError {
    path: string;
    message: string;
}

const typeOf = (value: unknown): string => {
    if (value === null) return 'null';
    if (Array.isArray(value)) return 'array';
    return typeof value;
};

const matchesType = (value: unknown, type: string): boolean => {
    const t = typeOf(value);
    if (type === 'integer') return t === 'number' && Number.isInteger(value as number);
    if (type === 'number') return t === 'number';
    return t === type;
};

export function validateAgainstSchema(
    value: unknown,
    schema: JSONSchema,
    path = '$',
    errors: ValidationError[] = []
): ValidationError[] {
    if (schema.type && !matchesType(value, schema.type)) {
        errors.push({ path, message: `se esperaba ${schema.type}, llegó ${typeOf(value)}` });
        return errors; // type mismatch makes deeper checks meaningless
    }

    if (schema.enum && !schema.enum.includes(value as string | number)) {
        errors.push({
            path,
            message: `valor "${String(value)}" no permitido; opciones: ${schema.enum.map(String).join(' | ')}`,
        });
    }

    if (typeof value === 'number') {
        if (schema.minimum !== undefined && value < schema.minimum) {
            errors.push({ path, message: `${value} < mínimo ${schema.minimum}` });
        }
        if (schema.maximum !== undefined && value > schema.maximum) {
            errors.push({ path, message: `${value} > máximo ${schema.maximum}` });
        }
    }

    if (typeof value === 'string' && schema.pattern) {
        if (!new RegExp(schema.pattern).test(value)) {
            errors.push({ path, message: `"${value}" no cumple el patrón ${schema.pattern}` });
        }
    }

    if (schema.type === 'object' && typeOf(value) === 'object') {
        const obj = value as Record<string, unknown>;
        for (const key of schema.required ?? []) {
            if (obj[key] === undefined) {
                errors.push({ path: `${path}.${key}`, message: 'campo obligatorio ausente' });
            }
        }
        for (const [key, sub] of Object.entries(schema.properties ?? {})) {
            if (obj[key] !== undefined) {
                validateAgainstSchema(obj[key], sub, `${path}.${key}`, errors);
            }
        }
        if (schema.additionalProperties === false && schema.properties) {
            for (const key of Object.keys(obj)) {
                if (!(key in schema.properties)) {
                    errors.push({ path: `${path}.${key}`, message: 'propiedad no reconocida' });
                }
            }
        }
    }

    if (schema.type === 'array' && Array.isArray(value) && schema.items) {
        value.forEach((item, i) => validateAgainstSchema(item, schema.items!, `${path}[${i}]`, errors));
    }

    return errors;
}

export function formatErrors(errors: ValidationError[]): string {
    return errors.map(e => `${e.path}: ${e.message}`).join('; ');
}
