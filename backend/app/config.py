import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_SQL_ID = 2**63 - 1


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('DATA_DIR', str(ROOT / 'data'))))
    database_url: str | None = None
    jwt_secret: str | None = field(default_factory=lambda: os.getenv('JWT_SECRET'))
    token_hours: int = 12
    llm_base_url: str = field(default_factory=lambda: os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'))
    llm_api_key: str = field(default_factory=lambda: os.getenv('LLM_API_KEY', ''))
    llm_model: str = field(default_factory=lambda: os.getenv('LLM_MODEL', ''))
    agent_quiet_seconds: float = 3
    agent_max_seconds: float = 15
    agent_timeout_seconds: float = 60
    max_upload_bytes: int = 20 * 1024 * 1024
    cors_origins: list[str] = field(default_factory=lambda: ['http://localhost:5173', 'http://127.0.0.1:5173'])

    @property
    def ai_ready(self):
        return bool(self.llm_api_key.strip() and self.llm_model.strip())

    def prepare(self):
        import secrets
        self.data_dir = Path(self.data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'files').mkdir(exist_ok=True)
        if not self.database_url:
            self.database_url = f'sqlite:///{(self.data_dir / "collaboration.db").as_posix()}'
        if not self.jwt_secret:
            key_file = self.data_dir / 'jwt.key'
            try:
                with key_file.open('x', encoding='ascii') as f:
                    f.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
            self.jwt_secret = key_file.read_text(encoding='ascii').strip()
        if len(self.jwt_secret) < 32:
            raise ValueError('JWT_SECRET 至少需要 32 个字符')
        return self
