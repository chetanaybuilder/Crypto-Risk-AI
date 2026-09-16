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
