import asyncpg
import logging
from utils.encryption import decrypt_data, reencrypt_if_needed
from utils.errors import DatabaseError, ConfigurationError, EncryptionError
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
database_pool = None

logger = logging.getLogger(__name__)


async def initialize_database():
    global database_pool

    if not DATABASE_URL:
        raise ConfigurationError("DATABASE_URL is not set in environment variables.")

    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
    except Exception as e:
        raise DatabaseError("Could not connect to the database.") from e

    try:
        async with pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                guild_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                product_secret TEXT NOT NULL,
                role_id TEXT,
                PRIMARY KEY (guild_id, product_name)
            )
            """)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_message (
                guild_id TEXT NOT NULL PRIMARY KEY,
                message_id TEXT,
                channel_id TEXT
            )
            """)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS verified_licenses (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                verified_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, guild_id, product_name)
            )
            """)
            await conn.execute("""
            ALTER TABLE verified_licenses ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ DEFAULT NOW()
            """)
            await conn.execute("""
            ALTER TABLE verified_licenses DROP COLUMN IF EXISTS license_key
            """)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS blacklisted_guilds (
                guild_id TEXT PRIMARY KEY,
                reason   TEXT,
                added_at TIMESTAMPTZ DEFAULT NOW()
            )
            """)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_role_permissions (
                guild_id   TEXT NOT NULL,
                role_id    TEXT NOT NULL,
                permission TEXT NOT NULL,
                PRIMARY KEY (guild_id, role_id, permission)
            )
            """)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id          SERIAL PRIMARY KEY,
                guild_id    TEXT NOT NULL,
                guild_name  TEXT,
                author_id   TEXT NOT NULL,
                author_name TEXT,
                subject     TEXT,
                message     TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
            """)
            # Must be created here, not in the server_log cog: the ALTER below runs on
            # startup and crashed on fresh databases when the table didn't exist yet.
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS server_log_channels (
                guild_id   TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                permission_warned BOOLEAN DEFAULT FALSE
            )
            """)
            await conn.execute("""
            ALTER TABLE server_log_channels ADD COLUMN IF NOT EXISTS permission_warned BOOLEAN DEFAULT FALSE
            """)
    except asyncpg.PostgresError as e:
        await pool.close()
        raise DatabaseError("Failed to initialize database schema.") from e

    database_pool = pool
    logger.info("Database initialized.")


async def get_setting(key: str, default: str = "") -> str:
    try:
        async with (await get_database_pool()).acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = $1", key)
        return row["value"] if row else default
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to read setting '{key}'.") from e


async def set_setting(key: str, value: str):
    try:
        async with (await get_database_pool()).acquire() as conn:
            await conn.execute("""
                INSERT INTO bot_settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2
            """, key, value)
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to write setting '{key}'.") from e


async def get_database_pool():
    if database_pool is None:
        raise DatabaseError("Database not initialized. Call `initialize_database` first.")
    return database_pool


async def get_role_permissions(guild_id, role_id) -> set:
    # Every capability granted to a single role, used to pre-tick the /permissions menu.
    try:
        async with (await get_database_pool()).acquire() as conn:
            rows = await conn.fetch(
                "SELECT permission FROM guild_role_permissions WHERE guild_id = $1 AND role_id = $2",
                str(guild_id), str(role_id)
            )
        return {row["permission"] for row in rows}
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to fetch permissions for role {role_id}.") from e


async def set_role_permissions(guild_id, role_id, permissions):
    # Replace the role's entire permission set atomically (the menu submits a full selection).
    try:
        async with (await get_database_pool()).acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM guild_role_permissions WHERE guild_id = $1 AND role_id = $2",
                    str(guild_id), str(role_id)
                )
                if permissions:
                    await conn.executemany(
                        "INSERT INTO guild_role_permissions (guild_id, role_id, permission) VALUES ($1, $2, $3)",
                        [(str(guild_id), str(role_id), perm) for perm in permissions]
                    )
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to set permissions for role {role_id}.") from e


async def save_feedback(guild_id, guild_name, author_id, author_name, subject, message):
    # Persist a feedback/suggestion entry for the developer to review in the admin panel.
    try:
        async with (await get_database_pool()).acquire() as conn:
            await conn.execute(
                """
                INSERT INTO feedback (guild_id, guild_name, author_id, author_name, subject, message)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                str(guild_id), guild_name, str(author_id), author_name, subject, message
            )
    except asyncpg.PostgresError as e:
        raise DatabaseError("Failed to save feedback.") from e


async def get_role_ids_with_permission(guild_id, permission) -> set:
    # All role IDs granted a given capability, used to authorize an incoming command.
    try:
        async with (await get_database_pool()).acquire() as conn:
            rows = await conn.fetch(
                "SELECT role_id FROM guild_role_permissions WHERE guild_id = $1 AND permission = $2",
                str(guild_id), permission
            )
        return {row["role_id"] for row in rows}
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to fetch roles for permission '{permission}'.") from e


async def fetch_product_names(guild_id) -> list:
    # Names only — no secrets touched. Decryption happens per-product in
    # fetch_product_secret so one corrupt record can't break the whole guild.
    try:
        async with (await get_database_pool()).acquire() as conn:
            rows = await conn.fetch(
                "SELECT product_name FROM products WHERE guild_id = $1 ORDER BY product_name", guild_id
            )
        return [row["product_name"] for row in rows]
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to fetch products for guild {guild_id}.") from e


async def fetch_product_secret(guild_id, product_name) -> str | None:
    # Decrypts exactly one product's secret, at the moment it's needed.
    # Returns None if the product doesn't exist. Raises EncryptionError if the
    # record can't be decrypted — callers surface that for this product only.
    try:
        async with (await get_database_pool()).acquire() as conn:
            row = await conn.fetchrow(
                "SELECT product_secret FROM products WHERE guild_id = $1 AND product_name = $2",
                guild_id, product_name
            )
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to fetch product '{product_name}' for guild {guild_id}.") from e
    if row is None:
        return None
    return decrypt_data(row["product_secret"])


async def save_verified_license(user_id, guild_id, product_name):
    try:
        async with (await get_database_pool()).acquire() as conn:
            await conn.execute(
                """
                INSERT INTO verified_licenses (user_id, guild_id, product_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, guild_id, product_name)
                DO NOTHING
                """,
                str(user_id), str(guild_id), product_name
            )
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to save verified license for user {user_id}.") from e


async def get_verified_license(user_id, guild_id, product_name) -> bool:
    try:
        async with (await get_database_pool()).acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM verified_licenses
                WHERE user_id = $1 AND guild_id = $2 AND product_name = $3
                """,
                str(user_id), str(guild_id), product_name
            )
            return row is not None
    except asyncpg.PostgresError as e:
        raise DatabaseError(f"Failed to check verified license for user {user_id}.") from e


async def run_auto_rotation():
    logger.info("Checking for data validation and key rotation...")

    pool = await get_database_pool()
    rotated_count = 0

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id, product_name, product_secret FROM products")
            for row in rows:
                original_secret = row["product_secret"]
                try:
                    new_secret = reencrypt_if_needed(original_secret)
                except EncryptionError as e:
                    logger.error(
                        f"[Key Rotation] Failed to re-encrypt product '{row['product_name']}' "
                        f"in guild {row['guild_id']}: {e}"
                    )
                    continue
                if original_secret != new_secret:
                    await conn.execute(
                        "UPDATE products SET product_secret = $1 WHERE guild_id = $2 AND product_name = $3",
                        new_secret, row["guild_id"], row["product_name"]
                    )
                    rotated_count += 1
    except asyncpg.PostgresError as e:
        raise DatabaseError("Key rotation failed during database operation.") from e

    if rotated_count > 0:
        logger.info(f"SECURITY ROTATION: Re-encrypted {rotated_count} records with the new key.")
    else:
        logger.info("Database is already fully encrypted with the latest key.")
