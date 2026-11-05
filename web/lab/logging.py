import logging
import re


class RedactRecoveryFilter(logging.Filter):
    def filter(self, record):
        # Django's development access logger otherwise prints recovery link tokens.
        message = record.getMessage()
        record.msg = re.sub(r"/recovery/[^\s?\"]+", "/recovery/[redacted]", message)
        record.args = ()
        return True
