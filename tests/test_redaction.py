import io
import agent
import logging


def test_traceback_redaction():
    secret = "<MY_TEST_SECRET_123>" 
    if secret not in agent._SENSITIVE_VALUES:
        agent._SENSITIVE_VALUES.append(secret)

    logger = logging.getLogger("playlist_agent")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(agent.RedactingFormatter("%(levelname)s: %(message)s\n%(exc_text)s"))
    logger.addHandler(handler)

    try:
        try:
            raise ValueError(f"An error occurred with secret {secret}")
        except Exception:
            logger.exception("An error occurred")

        output = stream.getvalue()
        assert secret not in output
        assert "[REDACTED]" in output
    finally:
        logger.removeHandler(handler)
        if secret in agent._SENSITIVE_VALUES:
            agent._SENSITIVE_VALUES.remove(secret)
