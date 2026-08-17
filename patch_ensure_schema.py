from pathlib import Path
import re

p = Path(r"services/post-migration-collector/src/post_migration/store.py")
src = p.read_text(encoding="utf-8")

new = '''    async def ensure_schema(self, sql_path: str | None = None) -> None:
        """Skip if tables already exist."""
        async with self._sessions() as session:
            exists = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'migration_tracks'
                        """
                    )
                )
            ).first()
            if exists:
                logger.info("store.schema_present")
                return
            logger.warning("store.schema_missing_run_sql_manually")

'''

src2, n = re.subn(
    r"    async def ensure_schema\(self.*?(?=\n    async def )",
    new,
    src,
    count=1,
    flags=re.S,
)
print("replacements", n)
if n != 1:
    raise SystemExit("ensure_schema pattern did not match")
p.write_text(src2, encoding="utf-8")
print("ok")
