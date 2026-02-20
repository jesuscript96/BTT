'use client'

import { useState } from 'react'
import { BookOpen, ChevronRight } from 'lucide-react'

const tutorials = [
    {
        id: 'create-strategy',
        title: 'Analiza el mercado, crea tu estrategia y corre el backtest',
        description: 'Aprende paso a paso cómo usar el Strategy Builder para crear una estrategia demo y ejecutar un backtest completo.',
        embedUrl: 'https://scribehow.com/embed/How_to_Create_a_Demo_Strategy_in_My_Strategy_Builder__O5m_CCrVTKe12QJ-mD9TFg',
    },
]

export default function TutorialsPage() {
    const [activeTutorial, setActiveTutorial] = useState(tutorials[0].id)

    const current = tutorials.find(t => t.id === activeTutorial)!

    return (
        <div className="flex h-screen bg-background overflow-hidden transition-colors duration-300">
            {/* Left Panel - Tutorial List */}
            <div className="w-80 border-r border-border flex-shrink-0 overflow-y-auto bg-sidebar/30">
                <div className="p-4 border-b border-border/50">
                    <div className="flex items-center gap-2.5">
                        <BookOpen className="h-5 w-5 text-foreground/70" />
                        <h2 className="text-sm font-bold text-foreground uppercase tracking-wider">
                            Tutoriales
                        </h2>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
                        Guías interactivas para dominar la plataforma.
                    </p>
                </div>

                <div className="p-2 space-y-1">
                    {tutorials.map((tutorial) => (
                        <button
                            key={tutorial.id}
                            onClick={() => setActiveTutorial(tutorial.id)}
                            className={`w-full text-left px-3 py-3 rounded-lg transition-all group ${activeTutorial === tutorial.id
                                    ? 'bg-foreground/10 border border-border'
                                    : 'hover:bg-sidebar-hover border border-transparent'
                                }`}
                        >
                            <div className="flex items-start gap-2.5">
                                <ChevronRight className={`h-4 w-4 mt-0.5 flex-shrink-0 transition-transform ${activeTutorial === tutorial.id
                                        ? 'text-foreground rotate-90'
                                        : 'text-muted-foreground/50'
                                    }`} />
                                <div className="min-w-0">
                                    <p className={`text-sm font-medium leading-snug ${activeTutorial === tutorial.id
                                            ? 'text-foreground'
                                            : 'text-sidebar-foreground/70 group-hover:text-foreground'
                                        }`}>
                                        {tutorial.title}
                                    </p>
                                    <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed line-clamp-2">
                                        {tutorial.description}
                                    </p>
                                </div>
                            </div>
                        </button>
                    ))}
                </div>
            </div>

            {/* Main Panel - Embedded Tutorial */}
            <div className="flex-1 overflow-y-auto bg-background/50">
                <div className="p-6">
                    {/* Tutorial Header */}
                    <div className="mb-6">
                        <h1 className="text-lg font-bold text-foreground">
                            {current.title}
                        </h1>
                        <p className="text-sm text-muted-foreground mt-1">
                            {current.description}
                        </p>
                    </div>

                    {/* Embed Container */}
                    <div className="rounded-xl border border-border bg-sidebar/30 overflow-hidden">
                        <iframe
                            src={current.embedUrl}
                            width="100%"
                            height="680"
                            allow="fullscreen"
                            style={{
                                border: 0,
                                minHeight: 480,
                                display: 'block',
                            }}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
