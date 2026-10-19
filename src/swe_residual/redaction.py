"""Use the artifact protection integrated into the vendored Harbor trial."""

from harbor.utils.redaction import redact, scrub_directory, secrets_in, sensitive

__all__ = ["redact", "scrub_directory", "secrets_in", "sensitive", "trial_class"]


def trial_class():
    from harbor.trial.trial import Trial

    return Trial
