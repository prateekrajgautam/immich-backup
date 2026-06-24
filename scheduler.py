"""
scheduler.py
Wraps APScheduler so we can enable/disable/reconfigure the cron schedule
at runtime from the web UI without restarting the app.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config as cfg_module

_scheduler = BackgroundScheduler()
_job_id = "immich_backup_job"
_run_fn = None  # set by app.py to avoid circular import


def init_scheduler(run_fn):
    global _run_fn
    _run_fn = run_fn
    _scheduler.start()
    apply_schedule_from_config()


def _job_wrapper():
    if _run_fn:
        _run_fn(trigger="scheduled")


def apply_schedule_from_config():
    cfg = cfg_module.load_config()
    if _scheduler.get_job(_job_id):
        _scheduler.remove_job(_job_id)
    if cfg.get("schedule_enabled") and cfg.get("schedule_cron"):
        trigger = CronTrigger.from_crontab(cfg["schedule_cron"])
        _scheduler.add_job(_job_wrapper, trigger, id=_job_id, replace_existing=True)


def get_next_run_time():
    job = _scheduler.get_job(_job_id)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None
