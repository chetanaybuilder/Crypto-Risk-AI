/**
 * Centralized Client-Side State Container.
 * Manages reactive UI state, active report payload, polling timers, and async job correlation.
 */
export const state = {
    token: null,
    user: null,
    latestReport: null,
    currentReportId: null,
    currentSymbol: null,

    livePollTimer: null,
    liveRequestId: 0,
    isLiveRequestInFlight: false,

    isAnalyzing: false,

    activeJobId: null,
    jobPollTimer: null,
    jobPollStartedAt: 0
};
