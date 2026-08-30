document.addEventListener("DOMContentLoaded", () => {

    /*
    ==========================================================
    CRYPTORISK AI
    Dashboard Interaction Engine
    ==========================================================
    */

    const input = document.querySelector(
        'input[name="token_symbol"]'
    );

    const form = document.querySelector(
        ".search-card form"
    );

    const overlay = document.getElementById(
        "analysisProgress"
    );

    const progressFill = document.getElementById(
        "progressFill"
    );

    const progressPercent = document.getElementById(
        "progressPercent"
    );

    const progressMessage = document.getElementById(
        "progressMessage"
    );

    const progressStage = document.getElementById(
        "progressStage"
    );

    const progressStatuses =
        document.querySelectorAll(
            ".progress-status"
        );


    /*
    ==========================================================
    TOKEN INPUT
    ==========================================================
    */

    if (input) {

        input.addEventListener(
            "input",
            () => {

                input.value = input.value
                    .toUpperCase()
                    .replace(
                        /[^A-Z0-9._-]/g,
                        ""
                    );

            }
        );

    }


    /*
    ==========================================================
    PROGRESS ENGINE
    ==========================================================
    */

    let progressTimer = null;

    const progressStages = [
        {
            percent: 18,
            stage: "INITIALIZING",
            message:
                "Preparing cryptocurrency intelligence request...",
            active: 0
        },
        {
            percent: 38,
            stage: "RESEARCHING",
            message:
                "Building the asset risk intelligence context...",
            active: 0
        },
        {
            percent: 62,
            stage: "AI ANALYSIS",
            message:
                "Gemini is evaluating risks and market signals...",
            active: 1
        },
        {
            percent: 82,
            stage: "STRUCTURING",
            message:
                "Structuring your intelligence report...",
            active: 2
        },
        {
            percent: 94,
            stage: "SECURING",
            message:
                "Saving your analysis securely...",
            active: 3
        }
    ];


    function updateProgress(stageData) {

        if (!progressFill) {
            return;
        }

        progressFill.style.width =
            `${stageData.percent}%`;

        if (progressPercent) {
            progressPercent.textContent =
                `${stageData.percent}%`;
        }

        if (progressMessage) {
            progressMessage.textContent =
                stageData.message;
        }

        if (progressStage) {
            progressStage.textContent =
                stageData.stage;
        }


        progressStatuses.forEach(
            (item, index) => {

                item.classList.remove(
                    "active",
                    "complete"
                );

                if (
                    index <
                    stageData.active
                ) {
                    item.classList.add(
                        "complete"
                    );
                }

                if (
                    index ===
                    stageData.active
                ) {
                    item.classList.add(
                        "active"
                    );
                }

            }
        );

    }


    function startProgress() {

        if (!overlay) {
            return;
        }

        overlay.classList.add(
            "is-visible"
        );

        overlay.setAttribute(
            "aria-hidden",
            "false"
        );

        document.body.classList.add(
            "analysis-running"
        );

        let currentStage = 0;

        updateProgress(
            progressStages[0]
        );

        progressTimer = setInterval(
            () => {

                if (
                    currentStage <
                    progressStages.length - 1
                ) {

                    currentStage++;

                    updateProgress(
                        progressStages[
                            currentStage
                        ]
                    );

                } else {

                    clearInterval(
                        progressTimer
                    );

                }

            },
            1600
        );

    }


    /*
    ==========================================================
    ANALYSIS FORM
    ==========================================================
    */

    if (form) {

        form.addEventListener(
            "submit",
            (event) => {

                const button =
                    form.querySelector(
                        ".analyze-button"
                    );

                if (!button) {
                    return;
                }


                const token =
                    input
                        ? input.value.trim()
                        : "";


                if (!token) {
                    return;
                }


                /*
                Prevent double submissions.
                */

                if (
                    form.dataset.submitting ===
                    "true"
                ) {

                    event.preventDefault();

                    return;

                }


                form.dataset.submitting =
                    "true";


                button.classList.add(
                    "is-loading"
                );

                button.disabled = true;


                const text =
                    button.querySelector(
                        "span:first-child"
                    );

                if (text) {
                    text.textContent =
                        "Analyzing";
                }


                startProgress();

            }
        );

    }


    /*
    ==========================================================
    DELETE CONFIRMATION
    ==========================================================
    */

    const deleteButtons =
        document.querySelectorAll(
            "[data-delete-report]"
        );


    deleteButtons.forEach(
        (button) => {

            button.addEventListener(
                "click",
                (event) => {

                    const confirmed =
                        window.confirm(
                            "Delete this analysis report? This cannot be undone."
                        );


                    if (!confirmed) {

                        event.preventDefault();

                        return;

                    }


                    button.disabled = true;

                    button.textContent =
                        "Deleting...";

                }
            );

        }
    );


    /*
    ==========================================================
    3D POINTER EFFECT
    ==========================================================
    */

    const cards =
        document.querySelectorAll(
            ".search-card, " +
            ".intelligence-report, " +
            ".history-card, " +
            ".report-panel, " +
            ".metric-card, " +
            ".risk-hero-card"
        );


    cards.forEach(
        (card) => {

            card.addEventListener(
                "pointermove",
                (event) => {

                    /*
                    Keep the effect subtle.
                    It enhances the existing CSS
                    instead of fighting it.
                    */

                    const rect =
                        card.getBoundingClientRect();

                    const x =
                        event.clientX -
                        rect.left;

                    const y =
                        event.clientY -
                        rect.top;

                    const rotateX =
                        (
                            (y / rect.height) -
                            0.5
                        ) * -2;

                    const rotateY =
                        (
                            (x / rect.width) -
                            0.5
                        ) * 2;


                    card.style.setProperty(
                        "--mouse-x",
                        `${x}px`
                    );

                    card.style.setProperty(
                        "--mouse-y",
                        `${y}px`
                    );

                    card.style.transform =
                        `perspective(1000px)
                         rotateX(${rotateX}deg)
                         rotateY(${rotateY}deg)
                         translateZ(0)`;

                }
            );


            card.addEventListener(
                "pointerleave",
                () => {

                    card.style.transform =
                        "";

                }
            );

        }
    );


    /*
    ==========================================================
    AUTO HIDE FLASH MESSAGES
    ==========================================================
    */

    const flashes =
        document.querySelectorAll(
            ".flash"
        );


    flashes.forEach(
        (flash) => {

            setTimeout(
                () => {

                    flash.style.opacity =
                        "0";

                    flash.style.transform =
                        "translateY(-8px)";

                    setTimeout(
                        () => {
                            flash.remove();
                        },
                        400
                    );

                },
                7000
            );

        }
    );

});