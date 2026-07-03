# KeyVerify

**A Discord bot for automated license verification of Payhip digital products.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Discord](https://img.shields.io/badge/Discord-Bot%20Ready-7289DA?logo=discord)](https://discord.com/oauth2/authorize?client_id=1314098590951673927&permissions=268511232&integration_type=0&scope=bot+applications.commands)

[Invite to your server](https://discord.com/oauth2/authorize?client_id=1314098590951673927&permissions=268511232&integration_type=0&scope=bot+applications.commands) — [Project page](https://fayelicious.net/projects/keyverify-bot/)

---

## Overview

KeyVerify lets Payhip sellers gate Discord roles behind license key verification. When a user verifies, the bot checks the key against the Payhip API and assigns the configured role. The verification result is recorded so roles can be automatically reapplied if a verified user rejoins. License keys are never stored.

---

## Features

- In-server verification via modal — no DMs or external links required
- Automatic role assignment and reassignment on rejoin
- Per-product configuration with optional auto-created roles
- License reset support for reactivations
- AES encryption (Fernet) for stored product secrets
- License keys are never stored — only the fact that verification occurred
- Key rotation: swap encryption keys without data loss
- Verification logging per server
- Rate limiting to prevent abuse
- Persistent verification buttons — survive bot restarts
- Per-role command permissions — delegate bot management without Discord admin rights
- Built-in feedback command wired to the developer

---

## Commands

| Command | Description |
|---|---|
| `/start_verification` | Post the verification button to a channel. |
| `/add_product` | Register a product with its Payhip secret and an optional role. |
| `/edit_product` | Rename a product or change its assigned role. |
| `/remove_product` | Remove a product from the server. |
| `/list_products` | List all registered products and their roles. |
| `/reset_key` | Reset the usage count of a license key on Payhip. |
| `/set_lchannel` | Set the channel where verification events are logged. |
| `/remove_user` | Revoke a user's access and remove their verification records. License disabling on Payhip must be done manually from your Payhip dashboard. |
| `/permissions` | Choose which commands a role may use (server owner only). |
| `/feedback` | Send feedback or a suggestion to the developer. |
| `/help` | Show available commands and support information. |

The server owner can always use every command. Everyone else needs a role that was granted access via `/permissions` — an interactive checklist where the owner picks, per role, exactly which commands it may use. `/permissions` itself is always owner-only.

---

## Setup

**1. Clone the repository**

```
git clone https://github.com/Fayelicious/KeyVerify.git
cd KeyVerify
```

**2. Install dependencies**

```
pip install -r requirements.txt
```

**3. Generate an encryption key**

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output — you'll need it in the next step.

**4. Create a `.env` file**

```
DISCORD_TOKEN=your_discord_bot_token
PAYHIP_API_KEY=your_payhip_api_key
DATABASE_URL=your_postgres_connection_url
ENCRYPTION_KEYS=your_generated_key
LOG_LEVEL=INFO
```

**5. Run the bot**

```
python bot.py
```

The bot requires the following Discord permissions: Manage Roles, Send Messages, Read Message History.

---

## Key Rotation

To replace your encryption key without losing access to stored data:

1. Generate a new key using the command in step 3 above.
2. Prepend it to `ENCRYPTION_KEYS`, separated by a comma:
   ```
   ENCRYPTION_KEYS=NEW_KEY,OLD_KEY
   ```
3. Restart the bot. On startup it will re-encrypt all records using the new key.
4. Once the log confirms rotation is complete, remove the old key from `.env`.

---

## Built With

- [disnake](https://github.com/DisnakeDev/disnake)
- [asyncpg](https://github.com/MagicStack/asyncpg)
- [aiohttp](https://github.com/aio-libs/aiohttp)
- [cryptography](https://github.com/pyca/cryptography)
- Python 3.11+

---

## Legal

- [Privacy Policy](https://fayelicious.net/legal/privacy-policy/)
- [Terms of Service](https://fayelicious.net/legal/terms-of-service/)

## Contact

Discord: `Fayelicious_`
