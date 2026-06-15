
import React from 'react';
import { EntryLogic, Timeframe } from '@/types/strategy';
import { LogicBuilder } from './ConditionBuilder';

interface Props {
    logic: EntryLogic;
    onChange: (logic: EntryLogic) => void;
    children?: React.ReactNode;
}

export const EntryLogicBuilder = React.memo(({ logic, onChange, children }: Props) => {
    return (
        <LogicBuilder
            title="Entrada Lógica"
            timeframe={logic.timeframe}
            onTimeframeChange={(tf) => onChange({ ...logic, timeframe: tf })}
            rootCondition={logic.root_condition}
            onConditionChange={(g) => onChange({ ...logic, root_condition: g })}
            accentColor="blue"
            candleDelay={logic.candle_delay}
            onCandleDelayChange={(delay) => onChange({ ...logic, candle_delay: delay })}
        >
            {children}
        </LogicBuilder>
    );
});
EntryLogicBuilder.displayName = "EntryLogicBuilder";
