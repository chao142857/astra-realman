"""Runner/worker timing only. Never projected into the model's frozen input."""

MODES = {
    'standard': {
        'episode_budget_s': 300, 'request_timeout_s': 30,
        'owner_watchdog_s': 600, 'startup_margin_s': None, 'cleanup_margin_s': None,
    },
    'qualification': {
        'episode_budget_s': 900, 'request_timeout_s': 90,
        'owner_watchdog_s': 1260, 'startup_margin_s': 300, 'cleanup_margin_s': 60,
    },
}


def timing_limits(mode):
    if mode not in MODES:
        raise ValueError('TIMING_MODE')
    return dict(MODES[mode])
