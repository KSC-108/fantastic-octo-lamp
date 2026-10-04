from octoquant.config import Config

SYMS = [f"S{i:02d}" for i in range(10)]


def make_small_cfg(root=None) -> Config:
    cfg = Config()
    cfg.model.min_train_days = 252
    cfg.model.retrain_every = 126
    cfg.model.max_iter = 60
    cfg.research.max_trials = 40
    if root is not None:
        cfg.runtime.db_path = str(root / "q.db")
        cfg.runtime.artifacts_dir = str(root / "artifacts")
        cfg.runtime.reports_dir = str(root / "reports")
        cfg.runtime.strategy_md = str(root / "strategy.md")
    return cfg
