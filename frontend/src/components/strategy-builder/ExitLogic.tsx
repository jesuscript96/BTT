
import React from 'react';
import { ExitLogic, Timeframe } from '@/types/strategy';
import { LogicBuilder } from './ConditionBuilder';

interface Props {
    logic: ExitLogic;
    onChange: (logic: ExitLogic) => void;
}

export const ExitLogicBuilder = ({ logic, onChange }: Props) => {
    return (
        <LogicBuilder
            title="Exit Logic"
            timeframe={logic.timeframe}
            onTimeframeChange={(tf) => onChange({ ...logic, timeframe: tf })}
            rootCondition={logic.root_condition}
            onConditionChange={(g) => onChange({ ...logic, root_condition: g })}
            accentColor="rose"
        />
    );
};
