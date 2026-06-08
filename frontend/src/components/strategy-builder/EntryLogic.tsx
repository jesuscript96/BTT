
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
            title="Entry Logic"
            timeframe={logic.timeframe}
            onTimeframeChange={(tf) => onChange({ ...logic, timeframe: tf })}
            rootCondition={logic.root_condition}
            onConditionChange={(g) => onChange({ ...logic, root_condition: g })}
            accentColor="blue"
        >
            {children}
        </LogicBuilder>
    );
});
EntryLogicBuilder.displayName = "EntryLogicBuilder";
