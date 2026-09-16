import logging
from services.db_service import get_analysis_job, update_analysis_job, save_analysis
from services.risk_engine import run_analysis

logger = logging.getLogger(__name__)

def execute_analysis_job(job_id):
    job = get_analysis_job(job_id, user_id=None)
    if not job:
        logger.error("Analysis worker could not find job: %s", job_id)
        return

    symbol = job["token_symbol"]
    chain_id = job.get("chain_id")
    contract_address = job.get("contract_address")
    user_id = job.get("user_id")

    update_analysis_job(job_id, status="running", started=True)

    def progress_callback(progress, stage, stage_title, message):
        update_analysis_job(
            job_id,
            progress=progress,
            stage=stage,
            stage_title=stage_title,
            message=message
        )

    try:
        report = run_analysis(
            symbol=symbol,
            chain_id=chain_id,
            contract_address=contract_address,
            progress_callback=progress_callback
        )
        
        # Save it as a finalized analysis linked to the user
        saved = save_analysis(user_id, symbol, report)

        update_analysis_job(
            job_id,
            status="completed",
            progress=100,
            report=report,
            meta={"analysis_id": saved},
            completed=True,
            message="Analysis complete."
        )

    except Exception as exc:
        logger.exception("Job %s failed.", job_id)
        
        error_msg = str(exc)
        if "timeout" in error_msg.lower():
            error_msg = "Data provider timeout. Please try again later."
            
        update_analysis_job(
            job_id,
            status="failed",
            error=error_msg,
            message="Analysis failed.",
            completed=True
        )
