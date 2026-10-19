"""Integrate after the LMS tool returns, before the final answering model."""
import os

from edu_context import compress_lms
from edu_context.model_client import JSONModelClient
from edu_context.text import EvidenceTextCompressor


def prepare_context(task, raw_json, *, student_uids=(), source_complete=None,
                    counter=None, summarize_comments=False):
    text_compressor = None
    if summarize_comments:
        # Explicit opt-in. The core never loads another project's .env file.
        client = JSONModelClient(
            api_key=os.environ['LMS_MODEL_API_KEY'],
            base_url=os.environ['LMS_MODEL_BASE_URL'],
            model=os.environ['LMS_MODEL_NAME'],
            max_calls=12,
        )
        text_compressor = EvidenceTextCompressor(client)
    result = compress_lms(
        task, raw_json, student_uids=student_uids,
        source_complete=source_complete, recover_truncated=True,
        token_counter=counter,
        comment_scope='summarize' if summarize_comments else 'auto',
        text_compressor=text_compressor,
    )
    if not result.within_budget:
        raise RuntimeError('Protected content exceeds context budget; narrow the query or split the task.')
    return result.context
