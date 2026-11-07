"""Cancellable process boundary for regexes with unbounded backtracking."""
import threading
from time import monotonic
from ..system.resident_worker import ResidentWorker


def match(request):
    from .studio_text_tools import _compile_needle, match_text_entries
    entries,query,locked=request
    pattern=_compile_needle(query[0],case_sensitive=query[3],whole_word=query[4],regex=True)
    return match_text_entries(entries,pattern,query[1],regex=True,body_only=query[6],locked_ids=locked)


def start_regex_job(entries,query,locked):
    # All arguments are frozen text records; no Qt object/project enters a
    # thread/process. This worker belongs solely to this one regex request.
    job={'cancel':threading.Event()}
    def run():
        worker=ResidentWorker('studio-regex-search')
        deadline=monotonic()+5
        try:
            result=worker.call('twobyteasr.studio.regex_search_job:match',(entries,query,locked),
                cancel_check=lambda:job['cancel'].is_set() or monotonic()>deadline)
            if result is None:
                job['error']='正则查询已取消或超过 5 秒，请缩小范围或简化表达式。'
            else:job['hits']=result
        except Exception as exc:job['error']=str(exc)[:200]
        finally:worker.close()
    job['thread']=threading.Thread(target=run,name='studio-regex-request',daemon=True)
    job['thread'].start()
    return job
