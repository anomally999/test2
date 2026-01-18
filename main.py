import os
import random
import sqlite3
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from datetime import timedelta, datetime as dt, timezone
from discord.utils import utcnow
import asyncio
import aiohttp
from contextlib import contextmanager
import json
from threading import Thread
import flask
import traceback

# ---------- ENVIRONMENT ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("PREFIX", "!")
DB_NAME = os.getenv("DB_PATH", "medieval_economy_ultimate.db")  # Configurable for Render persistent disk

# ---------- ROYAL TREASURY IMAGES ----------
TREASURY_SEAL_URL = "https://imgs.search.brave.com/ybyUdUFEw0dNXKCLGu2FuNAlJpvCTxkjXZUxOSFKcMM/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly90aHVt/YnMuZHJlYW1zdGlt/ZS5jb20vYi9yb3lh/bC1kZWNyZWUtdW52/ZWlsZWQtZXhxdWlz/aXRlLWdvbGQtc2Vh/bC12aW50YWdlLXN0/YXRpb25lcnktaGFu/ZHdyaXR0ZW4tbGV0/dGVyLWV4cGxvcmUt/b3B1bGVuY2UtcmVn/YWwtc3RlcC1iYWNr/LTM1MTI2NjUwOC5q/cGc"
COIN_GIF_URL = "https://media.giphy.com/media/3ohzdYrPBjW6cy2gla/giphy.gif"
CHEST_URL = "https://media.giphy.com/media/xT0GqfvuVpNqEf3jwA/giphy.gif"
ROYAL_CREST = "https://media.giphy.com/media/3o7aDcz6Y0fzWYvU5G/giphy.gif"
TOURNAMENT_URL = "https://media.giphy.com/media/l0HlNQ03jZUvjZWwU/giphy.gif"

# ---------- ECONOMY CONFIGURATION ----------
MAX_GOLD_NORMAL = 50000000000  # 50 billion gold cap for normal users
MAX_GOLD_ADMIN = 100000000000  # 100 billion gold cap for admins
ADMIN_MONTHLY_BONUS = 30000000000  # 30 billion gold monthly bonus for admins
LABOUR_COOLDOWN_HOURS = 1  # 1 hour labour cooldown
WEEKLY_GAMBLING_TRIES = 30  # 30 gambling attempts per week

# ---------- DATABASE CONNECTION MANAGER ----------
@contextmanager
def get_db_connection():
    """Context manager for database connections with enhanced persistence"""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-10000")  # 10MB cache
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

# ---------- COMPREHENSIVE DATA PERSISTENCE ----------
def save_config_to_db(key, value):
    """Save any configuration to database"""
    try:
        with get_db_connection() as db:
            # Use JSON for complex data types
            if isinstance(value, (dict, list, set)):
                value = json.dumps(value)
            elif isinstance(value, (discord.Role, discord.Member)):
                value = str(value.id)

            db.execute("""
            INSERT OR REPLACE INTO persistent_config (config_key, config_value, updated_at)
            VALUES (?, ?, ?)
            """, (key, str(value), utcnow().isoformat()))
            db.commit()
    except Exception as e:
        print(f"Error saving config {key}: {e}")

def load_config_from_db(key, default=None, type_cast=str):
    """Load configuration from database"""
    try:
        with get_db_connection() as db:
            row = db.execute("""
            SELECT config_value FROM persistent_config
            WHERE config_key = ?
            """, (key,)).fetchone()

            if row:
                value = row['config_value']
                if type_cast == dict or type_cast == list or type_cast == set:
                    return json.loads(value)
                elif type_cast == int:
                    return int(value)
                elif type_cast == bool:
                    return value.lower() == 'true'
                else:
                    return value
            return default
    except Exception as e:
        print(f"Error loading config {key}: {e}")
        return default

def save_giveaway_roles_to_db(guild_id, role_ids):
    """Save giveaway roles to database"""
    save_config_to_db(f"giveaway_roles_{guild_id}", role_ids)

def load_giveaway_roles_from_db(guild_id):
    """Load giveaway roles from database"""
    return load_config_from_db(f"giveaway_roles_{guild_id}", [], list)

def backup_all_data():
    """Create comprehensive backup of all data"""
    try:
        backup_dir = "backups"
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{backup_dir}/medieval_backup_{timestamp}.db"

        # Create backup
        with get_db_connection() as db:
            backup_db = sqlite3.connect(backup_file)
            with backup_db:
                db.backup(backup_db)
            backup_db.close()

        print(f"✅ Full database backup created: {backup_file}")
        return backup_file
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return None

def export_data_summary():
    """Export summary of all data for verification"""
    try:
        summary = {}

        with get_db_connection() as db:
            # Count all records
            tables = ['user_economy', 'shop_items', 'transactions', 'gambling_records',
                     'active_giveaways', 'user_inventory', 'admin_monthly_claims']

            for table in tables:
                count = db.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()['count']
                summary[table] = count

            # Get config count
            config_count = db.execute("SELECT COUNT(*) as count FROM persistent_config").fetchone()['count']
            summary['persistent_config'] = config_count

            # Get total gold in circulation
            total_gold = db.execute("SELECT SUM(gold) as total FROM user_economy").fetchone()['total'] or 0
            summary['total_gold_circulation'] = total_gold

            # Get active users
            active_users = db.execute("SELECT COUNT(DISTINCT user_id) as count FROM user_economy").fetchone()['count']
            summary['active_users'] = active_users

        # Save summary
        summary_file = "backups/data_summary.json"
        os.makedirs("backups", exist_ok=True)
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"✅ Data summary exported: {summary_file}")
        return summary
    except Exception as e:
        print(f"❌ Export failed: {e}")
        return None

# ---------- AUTHENTIC MEDIEVAL FLAIR ----------
MEDIEVAL_COLORS = {
    "gold": discord.Colour.gold(),
    "red": discord.Colour.dark_red(),
    "green": discord.Colour.dark_green(),
    "blue": discord.Colour.dark_blue(),
    "purple": discord.Colour.purple(),
    "orange": discord.Colour.dark_orange(),
    "teal": discord.Colour.teal(),
    "blurple": discord.Colour.blurple(),
    "yellow": discord.Colour.yellow(),
    "brown": discord.Colour.from_rgb(139, 69, 19),
}

# AUTHENTIC MEDIEVAL PHRASES
MEDIEVAL_GREETINGS = [
    "Hail and well met, good {title}!",
    "God's blessing upon thee, noble {title}!",
    "Well met in these fair lands, {title}!",
    "May fortune smile upon thee, {title}!",
    "The realm welcomes thy presence, {title}!",
    "Good morrow to thee, esteemed {title}!",
    "Blessings of the saints upon thee, {title}!",
    "By my troth, 'tis a fine day, {title}!",
]

MEDIEVAL_TITLES = [
    "sir", "good sir", "madam", "good dame", "lord", "lady",
    "master", "mistress", "goodman", "goodwife", "yeoman", "burgher"
]

ROYAL_PROCLAMATIONS = [
    "By royal decree and the authority of the crown!",
    "Hear ye, hear ye! Let it be proclaimed throughout the realm!",
    "By the ancient laws and customs of this fair kingdom!",
    "In accordance with the royal treasury and exchequer!",
    "As commanded by his most gracious majesty!",
    "Under the seal of the royal chamber and treasury!",
]

TOURNAMENT_PROCLAMATIONS = [
    "By the ancient laws of chivalry and tournament!",
    "Hear ye, hear ye! A grand tournament is proclaimed!",
    "Let the lists be cleared for noble combat!",
    "By decree of the royal heralds!",
    "As proclaimed by the king's own herald!",
    "Under the banner of fair tournament!",
]

TREASURY_GREETINGS = [
    "Welcome to the Royal Exchequer!",
    "Hail, merchant and trader of the realm!",
    "Fortune doth smile upon thee this day!",
    "May thy purse grow heavy with good coin!",
    "The economy of our kingdom doth thrive!",
    "Trade well and prosper, noble citizen!",
    "Enter freely into the royal treasury!",
    "The king's coin flows freely this day!",
]

DAILY_STIPEND_PHRASES = [
    "Receive this boon from the royal coffers!",
    "The crown's generosity knows no bounds!",
    "Thy loyalty is rewarded with royal gold!",
    "Blessings from the crown upon thee this day!",
    "The royal treasury grants thee thy daily stipend!",
    "Partake of the king's boundless generosity!",
    "May this stipend serve thee well, good subject!",
    "The exchequer smiles upon thee this day!",
]

WORK_PHRASES = [
    "Thou laborest diligently in the royal demesne!",
    "Thy service to the crown is duly noted!",
    "The guild masters are most pleased with thy work!",
    "Thy craftsmanship brings great honor to the realm!",
    "The harvest is bountiful thanks to thy efforts!",
    "Thy merchant skills have earned great profit!",
    "Well done, thou good and faithful servant!",
    "The bailiff commends thy diligent labour!",
]

GAMBLE_PHRASES = [
    "The dice are cast upon the table!",
    "Fortune favors the bold of heart!",
    "The cards reveal thy destined fate!",
    "The wheel of fortune spins freely!",
    "Thy luck is put to the test!",
    "The gods of chance smile upon thee!",
    "Let the games of chance begin!",
    "As the bones fall, so falls thy fate!",
]

TOURNAMENT_PHRASES = [
    "The lists are cleared for noble combat!",
    "Let the tournament begin in earnest!",
    "The heralds cry for champions to step forth!",
    "May the bravest soul claim victory!",
    "The tourney field awaits thy valor!",
    "Fortune favors the bold in tournament!",
    "Let chivalry and honor guide the contest!",
    "The royal box awaits the victor!",
]

def get_medieval_greeting(title=None):
    if not title:
        title = random.choice(MEDIEVAL_TITLES)
    return random.choice(MEDIEVAL_GREETINGS).format(title=title)

def get_royal_proclamation():
    return random.choice(ROYAL_PROCLAMATIONS)

def get_tournament_proclamation():
    return random.choice(TOURNAMENT_PROCLAMATIONS)

def get_treasury_greeting():
    return random.choice(TREASURY_GREETINGS)

def get_daily_stipend_phrase():
    return random.choice(DAILY_STIPEND_PHRASES)

def get_work_phrase():
    return random.choice(WORK_PHRASES)

def get_gamble_phrase():
    return random.choice(GAMBLE_PHRASES)

def get_tournament_phrase():
    return random.choice(TOURNAMENT_PHRASES)

def medieval_embed(title="", description="", color_name="gold", thumbnail_url=None):
    color = MEDIEVAL_COLORS.get(color_name, MEDIEVAL_COLORS["gold"])
    embed = discord.Embed(
        title=f"🏰 {title}" if "🏰" not in title and "💰" not in title and "⚔️" not in title else title,
        description=description,
        colour=color,
        timestamp=utcnow()
    )
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    else:
        embed.set_thumbnail(url=TREASURY_SEAL_URL)
    embed.set_footer(text="Recorded in the Royal Ledger by decree of the Crown")
    return embed

def medieval_response(message, success=True, extra=""):
    prefix = random.choice(["Forsooth,", "Verily,", "Marry,", "Prithee,", "Alack,", "Fie!"])
    suffix = random.choice(["good master.", "noble sir.", "fair dame.", "gentle soul.", "worthy friend."])
    color = "green" if success else "red"
    full_message = f"{prefix} {message} {suffix}".strip()
    if extra:
        full_message += f"\n\n{extra}"
    return medieval_embed(description=full_message, color_name=color)

def format_gold_amount(amount):
    """Format large gold amounts in medieval style"""
    if amount >= 1000000000:  # Billion
        return f"{amount / 1000000000:.1f} billion"
    elif amount >= 1000000:  # Million
        return f"{amount / 1000000:.1f} million"
    elif amount >= 1000:  # Thousand
        return f"{amount / 1000:.1f} thousand"
    else:
        return str(amount)

def format_time_remaining(seconds):
    """Format time remaining in medieval style"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)

    if hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''} and {minutes} minute{'s' if minutes != 1 else ''}"
    else:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

def get_user_highest_role(member):
    """Get user's highest Discord role excluding @everyone"""
    if not member or not member.roles:
        return None

    # Exclude @everyone role (position 0)
    real_roles = [role for role in member.roles if role.name != "@everyone"]

    if not real_roles:
        return None

    # Get highest role by position (highest position = highest in hierarchy)
    highest_role = max(real_roles, key=lambda r: r.position)
    return highest_role

def get_user_role_info(member):
    """Get comprehensive Discord role information for a user"""
    if not member or not member.roles:
        return "Discord Citizen", "No special station", None

    # Get all roles excluding @everyone, sorted by hierarchy (highest first)
    real_roles = [role for role in member.roles if role.name != "@everyone"]

    if not real_roles:
        return "Discord Citizen", "No special station", None

    # Sort by position (descending - highest role first)
    sorted_roles = sorted(real_roles, key=lambda r: r.position, reverse=True)
    highest_role = sorted_roles[0]

    # Create medieval-style hierarchy display
    role_count = len(sorted_roles)

    if role_count == 1:
        hierarchy_text = f"Holder of the {highest_role.mention} station"
    else:
        other_roles = sorted_roles[1:4]  # Show up to 3 additional roles
        other_mentions = [role.mention for role in other_roles]

        if len(sorted_roles) > 4:
            other_mentions.append(f"and {len(sorted_roles) - 4} more")

        hierarchy_text = f"Primary: {highest_role.mention}\nAlso: {', '.join(other_mentions)}"

    # Determine medieval title based on role position
    if highest_role.position >= 50:  # Very high roles
        medieval_title = "High Lord"
    elif highest_role.position >= 30:  # High roles
        medieval_title = "Noble Lord"
    elif highest_role.position >= 15:  # Medium-high roles
        medieval_title = "Esteemed Knight"
    elif highest_role.position >= 5:   # Medium roles
        medieval_title = "Honored Burgher"
    else:  # Lower roles
        medieval_title = "Guildsman"

    return medieval_title, hierarchy_text, highest_role

def get_week_start():
    """Get the start of the current week (Monday 00:00 UTC)"""
    now = utcnow()
    # Calculate days since Monday (0 = Monday, 6 = Sunday)
    days_since_monday = now.weekday()
    # Go back to Monday at 00:00 UTC
    week_start = now - timedelta(days=days_since_monday, hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)
    return week_start

def can_gamble_weekly(user_id, guild_id):
    """Check if user has gambling tries remaining this week"""
    try:
        week_start = get_week_start()

        with get_db_connection() as db:
            # Count gambling attempts this week
            row = db.execute("""
            SELECT COUNT(*) as count FROM gambling_records
            WHERE user_id=? AND guild_id=? AND timestamp >= ?
            """, (user_id, guild_id, week_start.isoformat())).fetchone()

            current_tries = row['count'] if row else 0
            remaining = max(0, WEEKLY_GAMBLING_TRIES - current_tries)

            return remaining > 0, remaining, current_tries
    except Exception as e:
        print(f"Error checking weekly gambling: {e}")
        return True, WEEKLY_GAMBLING_TRIES, 0

# ---------- BOT ----------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.reactions = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None, case_insensitive=True)
tree = bot.tree

# ---------- COMPREHENSIVE DATABASE INITIALIZATION ----------
def init_db():
    """Initialize COMPREHENSIVE persistent database with ALL data"""
    try:
        with get_db_connection() as db:
            print("🏰 Initializing COMPREHENSIVE PERSISTENT database...")

            # Create persistent configuration table first
            db.execute("""
            CREATE TABLE IF NOT EXISTS persistent_config (
                config_key TEXT PRIMARY KEY,
                config_value TEXT,
                updated_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")

            # Create all other tables
            tables_to_create = {
                'user_economy': """
                    CREATE TABLE IF NOT EXISTS user_economy (
                        user_id INTEGER NOT NULL,
                        guild_id INTEGER NOT NULL,
                        gold INTEGER DEFAULT 100,
                        daily_claimed TEXT,
                        work_cooldown TEXT,
                        gamble_wins INTEGER DEFAULT 0,
                        gamble_losses INTEGER DEFAULT 0,
                        total_gold_earned INTEGER DEFAULT 100,
                        total_gold_spent INTEGER DEFAULT 0,
                        noble_title TEXT DEFAULT 'Discord Citizen',
                        is_admin BOOLEAN DEFAULT 0,
                        admin_monthly_claimed TEXT,
                        PRIMARY KEY (user_id, guild_id)
                    )
                """,

                'transactions': """
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        guild_id INTEGER,
                        type TEXT,
                        amount INTEGER,
                        description TEXT,
                        timestamp TEXT,
                        balance_after INTEGER
                    )
                """,

                'shop_items': """
                    CREATE TABLE IF NOT EXISTS shop_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        name TEXT,
                        description TEXT,
                        price INTEGER,
                        role_id INTEGER,
                        role_name TEXT,
                        role_color TEXT,
                        role_position INTEGER,
                        stock INTEGER DEFAULT -1,
                        created_by INTEGER,
                        created_at TEXT
                    )
                """,

                'user_inventory': """
                    CREATE TABLE IF NOT EXISTS user_inventory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        guild_id INTEGER,
                        item_id INTEGER,
                        quantity INTEGER DEFAULT 1,
                        purchased_at TEXT
                    )
                """,

                'gambling_records': """
                    CREATE TABLE IF NOT EXISTS gambling_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        guild_id INTEGER,
                        game_type TEXT,
                        bet_amount INTEGER,
                        win_amount INTEGER,
                        outcome TEXT,
                        timestamp TEXT
                    )
                """,

                'active_giveaways': """
                    CREATE TABLE IF NOT EXISTS active_giveaways (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        channel_id INTEGER,
                        message_id INTEGER,
                        host_id INTEGER,
                        prize_name TEXT,
                        prize_amount INTEGER,
                        end_time TEXT,
                        winner_count INTEGER,
                        requirements TEXT,
                        status TEXT DEFAULT 'active'
                    )
                """,

                'giveaway_entries': """
                    CREATE TABLE IF NOT EXISTS giveaway_entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        giveaway_id INTEGER,
                        user_id INTEGER,
                        entered_at TEXT
                    )
                """,

                'admin_monthly_claims': """
                    CREATE TABLE IF NOT EXISTS admin_monthly_claims (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        guild_id INTEGER,
                        claim_month TEXT,
                        claimed_at TEXT,
                        amount INTEGER
                    )
                """,

                'data_backups': """
                    CREATE TABLE IF NOT EXISTS data_backups (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        backup_type TEXT,
                        backup_data TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """
            }

            # Create all tables
            for table_name, create_sql in tables_to_create.items():
                print(f"🗡️ Creating {table_name} table...")
                db.execute(create_sql)

            # Create indexes for better performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_user_economy_guild ON user_economy(guild_id)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, guild_id)",
                "CREATE INDEX IF NOT EXISTS idx_gambling_records_user ON gambling_records(user_id, guild_id)",
                "CREATE INDEX IF NOT EXISTS idx_gambling_records_timestamp ON gambling_records(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_shop_items_guild ON shop_items(guild_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_inventory_user ON user_inventory(user_id, guild_id)",
                "CREATE INDEX IF NOT EXISTS idx_giveaway_entries_giveaway ON giveaway_entries(giveaway_id)",
                "CREATE INDEX IF NOT EXISTS idx_active_giveaways_guild ON active_giveaways(guild_id)",
                "CREATE INDEX IF NOT EXISTS idx_persistent_config_key ON persistent_config(config_key)"
            ]

            for index_sql in indexes:
                db.execute(index_sql)

            # Load saved configuration
            load_all_saved_config()

            db.commit()
            print("✅ COMPREHENSIVE PERSISTENT Database created with ALL features!")

    except sqlite3.Error as e:
        print(f"❌ Database initialization error: {e}")
        raise

def load_all_saved_config():
    """Load all saved configuration from database"""
    try:
        # Load giveaway roles
        with get_db_connection() as db:
            rows = db.execute("""
            SELECT config_key, config_value FROM persistent_config
            WHERE config_key LIKE 'giveaway_roles_%'
            """).fetchall()

            for row in rows:
                guild_id = int(row['config_key'].replace('giveaway_roles_', ''))
                role_ids = json.loads(row['config_value'])
                GIVEAWAY_ROLES[guild_id] = role_ids

        print(f"✅ Loaded {len(GIVEAWAY_ROLES)} guilds' giveaway roles from database")
    except Exception as e:
        print(f"❌ Error loading saved config: {e}")

# ---------- GIVEAWAY ROLE STORAGE ----------
GIVEAWAY_ROLES = {}  # guild_id: [role_id1, role_id2, ...]

# ---------- ENHANCED MEDIEVAL ECONOMY FUNCTIONS ----------
def is_user_admin(user_id, guild_id):
    """Check if user has admin privileges"""
    try:
        with get_db_connection() as db:
            row = db.execute("""
            SELECT is_admin FROM user_economy
            WHERE user_id=? AND guild_id=?
            """, (user_id, guild_id)).fetchone()

            if row and row['is_admin']:
                return True

            # Also check if user has Administrator permission in Discord
            guild = bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member and member.guild_permissions.administrator:
                    # Update database to mark as admin
                    db.execute("""
                    UPDATE user_economy SET is_admin=1 WHERE user_id=? AND guild_id=?
                    """, (user_id, guild_id))
                    db.commit()
                    return True

            return False
    except Exception as e:
        print(f"Error checking admin status: {e}")
        return False

def get_user_balance(user_id, guild_id):
    """Get user's gold and stats - NO VAULT"""
    try:
        with get_db_connection() as db:
            row = db.execute("""
            SELECT gold, gamble_wins, gamble_losses, total_gold_earned, total_gold_spent, is_admin
            FROM user_economy
            WHERE user_id=? AND guild_id=?
            """, (user_id, guild_id)).fetchone()

            if row:
                return row['gold'], row['gamble_wins'], row['gamble_losses'], row['total_gold_earned'], row['total_gold_spent'], row['is_admin']
            else:
                # Create new user entry with starting gold
                db.execute("""
                INSERT INTO user_economy (user_id, guild_id, gold, total_gold_earned)
                VALUES (?, ?, 100, 100)
                """, (user_id, guild_id))
                db.commit()
                return 100, 0, 0, 100, 0, False
    except Exception as e:
        print(f"Error getting user balance: {e}")
        return 0, 0, 0, 0, 0, False

def get_gold_cap(user_id, guild_id):
    """Get user's gold cap based on admin status"""
    if is_user_admin(user_id, guild_id):
        return MAX_GOLD_ADMIN
    return MAX_GOLD_NORMAL

def update_user_balance(user_id, guild_id, gold_change, description=""):
    """Update user balance - NO VAULT, ONLY GOLD"""
    try:
        current_gold, wins, losses, total_earned, total_spent, is_admin = get_user_balance(user_id, guild_id)
        gold_cap = get_gold_cap(user_id, guild_id)

        # Calculate new gold with cap enforcement
        new_gold = max(0, current_gold + gold_change)
        new_gold = min(new_gold, gold_cap)  # Enforce gold cap

        # Update totals
        if gold_change > 0:
            new_total_earned = total_earned + gold_change
            new_total_spent = total_spent
        else:
            new_total_earned = total_earned
            new_total_spent = total_spent + abs(gold_change)

        with get_db_connection() as db:
            # Update balance
            db.execute("""
            UPDATE user_economy
            SET gold=?, total_gold_earned=?, total_gold_spent=?
            WHERE user_id=? AND guild_id=?
            """, (new_gold, new_total_earned, new_total_spent, user_id, guild_id))

            # Record transaction
            db.execute("""
            INSERT INTO transactions (user_id, guild_id, type, amount, description, timestamp, balance_after)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, guild_id, "balance_change", gold_change, description, utcnow().isoformat(), new_gold))

            db.commit()

        # Check if gold was capped
        actual_gold_change = new_gold - current_gold
        if actual_gold_change < gold_change:
            return new_gold, True  # Returns True if capped
        return new_gold, False

    except Exception as e:
        print(f"Error updating user balance: {e}")
        return current_gold, False

def can_claim_admin_monthly(user_id, guild_id):
    """Check if admin can claim monthly bonus"""
    try:
        with get_db_connection() as db:
            row = db.execute("""
            SELECT admin_monthly_claimed FROM user_economy
            WHERE user_id=? AND guild_id=?
            """, (user_id, guild_id)).fetchone()

            if not row or not row['admin_monthly_claimed']:
                return True

            last_claimed = dt.fromisoformat(row['admin_monthly_claimed']).replace(tzinfo=timezone.utc)
            time_since = utcnow() - last_claimed

            return time_since.total_seconds() >= 2592000  # 30 days
    except Exception as e:
        print(f"Error checking admin monthly claim: {e}")
        return True

def claim_admin_monthly_bonus(user_id, guild_id):
    """Claim monthly admin bonus (30 billion gold)"""
    try:
        if not is_user_admin(user_id, guild_id):
            return False, 0, "Only royal administrators may claim this bounty!"

        if not can_claim_admin_monthly(user_id, guild_id):
            return False, 0, "Thou hast already received thy monthly administrator's bounty!"

        # Check if user has admin role in Discord
        guild = bot.get_guild(guild_id)
        if not guild:
            return False, 0, "Guild not found!"

        member = guild.get_member(user_id)
        if not member or not member.guild_permissions.administrator:
            return False, 0, "Thou must have Administrator permissions to claim this bounty!"

        with get_db_connection() as db:
            # Update admin monthly claim
            db.execute("""
            UPDATE user_economy
            SET gold=gold+?, admin_monthly_claimed=?
            WHERE user_id=? AND guild_id=?
            """, (ADMIN_MONTHLY_BONUS, utcnow().isoformat(), user_id, guild_id))

            # Record transaction
            db.execute("""
            INSERT INTO transactions (user_id, guild_id, type, amount, description, timestamp, balance_after)
            VALUES (?, ?, 'admin_monthly', ?, 'Royal administrator monthly bounty', ?, ?)
            """, (user_id, guild_id, ADMIN_MONTHLY_BONUS, utcnow().isoformat(),
                  get_user_balance(user_id, guild_id)[0] + ADMIN_MONTHLY_BONUS))

            # Record in admin claims table
            current_month = dt.now().strftime("%Y-%m")
            db.execute("""
            INSERT INTO admin_monthly_claims (user_id, guild_id, claim_month, claimed_at, amount)
            VALUES (?, ?, ?, ?, ?)
            """, (user_id, guild_id, current_month, utcnow().isoformat(), ADMIN_MONTHLY_BONUS))

            db.commit()

        return True, ADMIN_MONTHLY_BONUS, ""

    except Exception as e:
        print(f"Error claiming admin monthly bonus: {e}")
        return False, 0, "An error befell the royal treasury!"

def can_claim_daily(user_id, guild_id):
    """Check if user can claim daily gold"""
    try:
        with get_db_connection() as db:
            row = db.execute("""
            SELECT daily_claimed FROM user_economy
            WHERE user_id=? AND guild_id=?
            """, (user_id, guild_id)).fetchone()

            if not row or not row['daily_claimed']:
                return True

            last_claimed = dt.fromisoformat(row['daily_claimed']).replace(tzinfo=timezone.utc)
            time_since = utcnow() - last_claimed

            return time_since.total_seconds() >= 86400  # 24 hours
    except Exception as e:
        print(f"Error checking daily claim: {e}")
        return True

def claim_daily(user_id, guild_id):
    """Claim daily royal stipend (3-7 gold)"""
    try:
        if not can_claim_daily(user_id, guild_id):
            return False, 0

        daily_amount = random.randint(3, 7)
        new_gold, capped = update_user_balance(user_id, guild_id, daily_amount, "Royal daily stipend")

        if capped:
            return True, daily_amount  # Still successful even if capped
        return True, daily_amount
    except Exception as e:
        print(f"Error claiming daily: {e}")
        return False, 0

def get_labour_cooldown_status(user_id, guild_id):
    """Check labour cooldown status with detailed info"""
    try:
        current_time = utcnow()

        # Check database cooldown
        with get_db_connection() as db:
            row = db.execute("""
            SELECT work_cooldown FROM user_economy
            WHERE user_id=? AND guild_id=?
            """, (user_id, guild_id)).fetchone()

            if not row or not row['work_cooldown']:
                return True, 0, "Ready to work"

            last_work = dt.fromisoformat(row['work_cooldown']).replace(tzinfo=timezone.utc)
            time_since = current_time - last_work
            cooldown_seconds = LABOUR_COOLDOWN_HOURS * 3600

            if time_since.total_seconds() >= cooldown_seconds:
                return True, 0, "Ready to work"
            else:
                remaining = cooldown_seconds - time_since.total_seconds()
                return False, remaining, format_time_remaining(remaining)
    except Exception as e:
        print(f"Error checking labour cooldown: {e}")
        return True, 0, "Ready to work"

def work(user_id, guild_id):
    """Work for honest wages (8-15 gold) with 1-hour individual cooldown"""
    try:
        can_work, remaining_time, status_msg = get_labour_cooldown_status(user_id, guild_id)

        if not can_work:
            return False, 0, remaining_time

        work_amount = random.randint(8, 15)
        new_gold, capped = update_user_balance(user_id, guild_id, work_amount, "Honest labour in the royal demesne")

        # Update work cooldown in database
        with get_db_connection() as db:
            db.execute("""
            UPDATE user_economy
            SET work_cooldown=?
            WHERE user_id=? AND guild_id=?
            """, (utcnow().isoformat(), user_id, guild_id))
            db.commit()

        if capped:
            return True, work_amount, 0  # Still successful even if capped, no remaining time
        return True, work_amount, 0

    except Exception as e:
        print(f"Error working: {e}")
        return False, 0, 0

def gamble(user_id, guild_id, amount, game_type="dice"):
    """Gamble gold with medieval games - NOW WITH WEEKLY LIMITS!"""
    try:
        # Check weekly gambling tries first
        can_gamble, remaining_tries, used_tries = can_gamble_weekly(user_id, guild_id)

        if not can_gamble:
            return False, 0, f"Thou hast exhausted thy weekly gambling allowance! Thou hast used all {WEEKLY_GAMBLING_TRIES} tries this week."

        current_gold, wins, losses, total_earned, total_spent, is_admin = get_user_balance(user_id, guild_id)
        gold_cap = get_gold_cap(user_id, guild_id)

        if amount <= 0:
            return False, 0, "Thou must wager a positive sum, good master!"

        if amount > current_gold:
            return False, 0, "Thy purse contains insufficient coin for such a wager!"

        # Check if user is at gold cap
        if current_gold >= gold_cap:
            return False, 0, f"Thy purse is already at the maximum of {format_gold_amount(gold_cap)} gold pieces!"

        # Medieval gambling games
        if game_type == "dice":
            win = random.random() < 0.5  # 50/50
            multiplier = 2 if win else 0

        elif game_type == "coin":
            win = random.random() < 0.48  # Slight house edge
            multiplier = 2 if win else 0

        elif game_type == "slots":
            roll = random.random()
            if roll < 0.05:      # 5% - Royal Flush
                multiplier = 10
                win = True
            elif roll < 0.15:    # 10% - Noble Pair
                multiplier = 3
                win = True
            elif roll < 0.45:    # 30% - Common Win
                multiplier = 2
                win = True
            else:                # 55% - Loss
                multiplier = 0
                win = False

        else:
            return False, 0, "Such games are unknown in our realm!"

        win_amount = int(amount * multiplier) if win else 0
        net_change = win_amount - amount

        # Update balance with cap check
        new_gold, capped = update_user_balance(user_id, guild_id, net_change, f"Gamed {amount} on {game_type} - {'Won' if win else 'Lost'}")

        # Update gambling stats
        with get_db_connection() as db:
            if win:
                db.execute("""
                UPDATE user_economy SET gamble_wins=gamble_wins+1
                WHERE user_id=? AND guild_id=?
                """, (user_id, guild_id))
            else:
                db.execute("""
                UPDATE user_economy SET gamble_losses=gamble_losses+1
                WHERE user_id=? AND guild_id=?
                """, (user_id, guild_id))

            # Record gambling
            db.execute("""
            INSERT INTO gambling_records (user_id, guild_id, game_type, bet_amount, win_amount, outcome, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, guild_id, game_type, amount, win_amount, "win" if win else "loss", utcnow().isoformat()))

            db.commit()

        if capped and win:
            return win, win_amount, f"Thy winnings were capped at {format_gold_amount(new_gold)} gold pieces!"

        # Add remaining tries information
        new_remaining = remaining_tries - 1
        tries_info = f"\n\n🎲 **Weekly Gambling**: {new_remaining}/{WEEKLY_GAMBLING_TRIES} tries remaining this week"

        return win, win_amount, tries_info

    except Exception as e:
        print(f"Error gambling: {e}")
        return False, 0, "An ill omen befell thy game!"

def transfer_gold(sender_id, receiver_id, guild_id, amount):
    """Transfer gold between subjects"""
    try:
        sender_gold, _, _, _, _, _ = get_user_balance(sender_id, guild_id)
        receiver_gold, _, _, _, _, receiver_is_admin = get_user_balance(receiver_id, guild_id)
        receiver_cap = get_gold_cap(receiver_id, guild_id)

        if amount <= 0:
            return False, "Thy sum must be positive, good master!"

        if amount > sender_gold:
            return False, "Thy purse contains insufficient coin!"

        if sender_id == receiver_id:
            return False, "Thou canst not pay thyself, good sir!"

        # Check if receiver would exceed cap
        if receiver_gold + amount > receiver_cap:
            return False, f"The recipient's purse cannot hold more than {format_gold_amount(receiver_cap)} gold pieces!"

        # Perform transfer
        update_user_balance(sender_id, guild_id, -amount, f"Paid {amount} gold to subject {receiver_id}")
        update_user_balance(receiver_id, guild_id, amount, f"Received {amount} gold from subject {sender_id}")

        return True, ""
    except Exception as e:
        print(f"Error transferring gold: {e}")
        return False, "The transfer failed most grievously!"

def get_economy_stats(user_id, guild_id):
    """Get comprehensive economy chronicles - NO VAULT"""
    try:
        with get_db_connection() as db:
            row = db.execute("""
            SELECT gold, gamble_wins, gamble_losses, total_gold_earned, total_gold_spent, is_admin
            FROM user_economy
            WHERE user_id=? AND guild_id=?
            """, (user_id, guild_id)).fetchone()

            if row:
                return dict(row)
            return None
    except Exception as e:
        print(f"Error getting economy stats: {e}")
        return None

def get_leaderboard(guild_id, limit=10):
    """Get the realm's wealthiest nobles - NO VAULT"""
    try:
        with get_db_connection() as db:
            rows = db.execute("""
            SELECT user_id, gold, gamble_wins, gamble_losses, total_gold_earned, total_gold_spent, is_admin
            FROM user_economy
            WHERE guild_id=?
            ORDER BY gold DESC
            LIMIT ?
            """, (guild_id, limit)).fetchall()

            return rows
    except Exception as e:
        print(f"Error getting leaderboard: {e}")
        return []

# ---------- REAL ROLE-BASED SHOP SYSTEM ----------
def add_shop_item(guild_id, name, description, price, role=None, stock=-1, created_by=None):
    """Add Discord role to the royal shop"""
    try:
        with get_db_connection() as db:
            role_id = role.id if role else None
            role_name = role.name if role else None
            role_color = str(role.color) if role else None
            role_position = role.position if role else 0

            db.execute("""
            INSERT INTO shop_items (guild_id, name, description, price, role_id, role_name, role_color, role_position, stock, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, name, description, price, role_id, role_name, role_color, role_position, stock, created_by, utcnow().isoformat()))

            db.commit()
            return True
    except Exception as e:
        print(f"Error adding shop item: {e}")
        return False

def get_shop_items(guild_id):
    """Get all items from the royal shop"""
    try:
        with get_db_connection() as db:
            rows = db.execute("""
            SELECT id, name, description, price, role_id, role_name, role_color, role_position, stock
            FROM shop_items
            WHERE guild_id=?
            ORDER BY role_position DESC, price ASC
            """, (guild_id,)).fetchall()

            return rows
    except Exception as e:
        print(f"Error getting shop items: {e}")
        return []

async def buy_item(user_id, guild_id, item_id, guild):
    """Purchase Discord role from royal shop"""
    try:
        with get_db_connection() as db:
            # Get item details
            item = db.execute("""
            SELECT * FROM shop_items
            WHERE id=? AND guild_id=?
            """, (item_id, guild_id)).fetchone()

            if not item:
                return False, "Such merchandise exists not in our realm!", None

            if item['stock'] == 0:
                return False, "This treasure is sold out, good master!", None

            user_gold, _, _, _, _, is_admin = get_user_balance(user_id, guild_id)
            gold_cap = get_gold_cap(user_id, guild_id)

            if user_gold < item['price']:
                return False, "Thy purse lacks sufficient coin for this purchase!", None

            # Check if purchase would exceed gold cap
            if user_gold - item['price'] > gold_cap:
                return False, f"Thy gold cannot exceed {format_gold_amount(gold_cap)} gold pieces!", None

            # Check if user already has this role
            member = guild.get_member(user_id)
            if member and item['role_id']:
                existing_role = guild.get_role(item['role_id'])
                if existing_role and existing_role in member.roles:
                    return False, f"Thou already possess the {existing_role.mention} station!", None

            # Deduct gold
            new_gold, capped = update_user_balance(user_id, guild_id, -item['price'], f"Purchased {item['name']} from royal shop")

            # Add to inventory
            db.execute("""
            INSERT INTO user_inventory (user_id, guild_id, item_id, purchased_at)
            VALUES (?, ?, ?, ?)
            """, (user_id, guild_id, item_id, utcnow().isoformat()))

            # Update stock if limited
            if item['stock'] > 0:
                db.execute("""
                UPDATE shop_items SET stock=stock-1 WHERE id=?
                """, (item_id,))

            db.commit()

            # Handle role assignment if item has a role
            if item['role_id']:
                if member:
                    role = guild.get_role(item['role_id'])
                    if role:
                        try:
                            await member.add_roles(role)
                            return True, item['name'], role.mention
                        except discord.Forbidden:
                            return True, item['name'], None
                        except discord.HTTPException:
                            return True, item['name'], None

            return True, item['name'], None
    except Exception as e:
        print(f"Error buying item: {e}")
        return False, "The purchase failed most grievously!", None

def get_user_inventory(user_id, guild_id):
    """Get user's purchased Discord roles"""
    try:
        with get_db_connection() as db:
            rows = db.execute("""
            SELECT si.name, si.description, si.price, si.role_name, si.role_color, si.role_position, ui.purchased_at
            FROM user_inventory ui
            JOIN shop_items si ON ui.item_id = si.id
            WHERE ui.user_id=? AND ui.guild_id=?
            ORDER BY ui.purchased_at DESC
            """, (user_id, guild_id)).fetchall()

            return rows
    except Exception as e:
        print(f"Error getting user inventory: {e}")
        return []

# ---------- MEDIEVAL GIVEAWAY SYSTEM ----------
def has_giveaway_permission(member, guild_id):
    """Check if member has giveaway host permission"""
    try:
        guild_roles = load_giveaway_roles_from_db(guild_id)
        if not guild_roles:
            return False

        member_role_ids = [role.id for role in member.roles]
        return any(role_id in member_role_ids for role_id in guild_roles)
    except Exception as e:
        print(f"Error checking giveaway permission: {e}")
        return False

def create_giveaway(guild_id, channel_id, message_id, host_id, prize_name, prize_amount, end_time, winner_count=1, requirements=None):
    """Create a new tournament/giveaway"""
    try:
        with get_db_connection() as db:
            db.execute("""
            INSERT INTO active_giveaways (guild_id, channel_id, message_id, host_id, prize_name, prize_amount, end_time, winner_count, requirements)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, channel_id, message_id, host_id, prize_name, prize_amount, end_time.isoformat(), winner_count, json.dumps(requirements) if requirements else None))

            db.commit()
            return True
    except Exception as e:
        print(f"Error creating giveaway: {e}")
        return False

def enter_giveaway(giveaway_id, user_id):
    """Enter a user into a tournament"""
    try:
        with get_db_connection() as db:
            # Check if already entered
            existing = db.execute("""
            SELECT id FROM giveaway_entries
            WHERE giveaway_id=? AND user_id=?
            """, (giveaway_id, user_id)).fetchone()

            if existing:
                return False, "Already entered"

            db.execute("""
            INSERT INTO giveaway_entries (giveaway_id, user_id, entered_at)
            VALUES (?, ?, ?)
            """, (giveaway_id, user_id, utcnow().isoformat()))

            db.commit()
            return True, "Entered successfully"
    except Exception as e:
        print(f"Error entering giveaway: {e}")
        return False, "Entry failed"

def get_giveaway_entries(giveaway_id):
    """Get all entries for a giveaway"""
    try:
        with get_db_connection() as db:
            rows = db.execute("""
            SELECT user_id FROM giveaway_entries
            WHERE giveaway_id=?
            """, (giveaway_id,)).fetchall()

            return [row['user_id'] for row in rows]
    except Exception as e:
        print(f"Error getting giveaway entries: {e}")
        return []

def end_giveaway(giveaway_id):
    """End a giveaway and select winners"""
    try:
        with get_db_connection() as db:
            # Get giveaway info
            giveaway = db.execute("""
            SELECT * FROM active_giveaways
            WHERE id=? AND status='active'
            """, (giveaway_id,)).fetchone()

            if not giveaway:
                return None, None

            # Get all entries
            entries = get_giveaway_entries(giveaway_id)

            if not entries:
                # Mark as ended with no winners
                db.execute("""
                UPDATE active_giveaways SET status='ended' WHERE id=?
                """, (giveaway_id,))
                db.commit()
                return [], giveaway

            # Select random winners
            winner_count = min(giveaway['winner_count'], len(entries))
            winners = random.sample(entries, winner_count)

            # Mark giveaway as ended
            db.execute("""
            UPDATE active_giveaways SET status='ended' WHERE id=?
            """, (giveaway_id,))

            # Award prizes to winners
            for winner_id in winners:
                update_user_balance(winner_id, giveaway['guild_id'], giveaway['prize_amount'], f"Won tournament: {giveaway['prize_name']}")

            db.commit()
            return winners, giveaway

    except Exception as e:
        print(f"Error ending giveaway: {e}")
        return None, None

def get_active_giveaways(guild_id):
    """Get all active giveaways for a guild"""
    try:
        with get_db_connection() as db:
            rows = db.execute("""
            SELECT * FROM active_giveaways
            WHERE guild_id=? AND status='active' AND datetime(end_time) > datetime('now')
            ORDER BY end_time ASC
            """, (guild_id,)).fetchall()

            return rows
    except Exception as e:
        print(f"Error getting active giveaways: {e}")
        return []

# ---------- AUTHENTIC MEDIEVAL PREFIX COMMANDS WITH ALL FEATURES ----------
@bot.command(name="purse")
@commands.guild_only()
async def purse_cmd(ctx, member: discord.Member = None):
    """Inspect thy purse and treasury - ULTIMATE with wins/losses & role hierarchy!"""
    try:
        member = member or ctx.author
        gold, wins, losses, total_earned, total_spent, is_admin = get_user_balance(member.id, ctx.guild.id)

        # Get real Discord role information
        medieval_title, hierarchy_text, highest_role = get_user_role_info(member)

        # Get weekly gambling status
        can_gamble, remaining_tries, used_tries = can_gamble_weekly(member.id, ctx.guild.id)

        embed = medieval_embed(
            title=f"💰 Royal Purse of {member.display_name}",
            description=f"{get_treasury_greeting()} As {medieval_title} of the realm, thy financial standing is thus:",
            color_name="gold"
        )

        embed.add_field(
            name="🏷️ Coin in Purse",
            value=f"**{format_gold_amount(gold)}** gold pieces",
            inline=False
        )

        # WINS/LOSSES TRACKING
        total_games = wins + losses
        if total_games > 0:
            win_rate = (wins / total_games) * 100
            embed.add_field(
                name="🎲 Gaming Record",
                value=f"**{wins}** victories | **{losses}** defeats\n**{win_rate:.1f}%** success rate",
                inline=True
            )

        # WEEKLY GAMBLING STATUS
        embed.add_field(
            name="🃏 Weekly Gambling",
            value=f"**{remaining_tries}**/{WEEKLY_GAMBLING_TRIES} tries remaining this week",
            inline=True
        )

        embed.add_field(
            name="📈 Lifetime Earnings",
            value=f"**{format_gold_amount(total_earned)}** gold pieces",
            inline=True
        )

        embed.add_field(
            name="📉 Lifetime Expenditures",
            value=f"**{format_gold_amount(total_spent)}** gold pieces",
            inline=True
        )

        embed.add_field(
            name="⚔️ Discord Station",
            value=f"**{highest_role.name if highest_role else 'Citizen'}** of the Realm",
            inline=False
        )

        # Show role hierarchy information
        if hierarchy_text:
            embed.add_field(
                name="🏰 Role Hierarchy",
                value=hierarchy_text,
                inline=False
            )

        # Show gold cap information
        cap_type = "Administrator" if is_admin else "Subject"
        embed.add_field(
            name="🏰 Royal Treasury Limit",
            value=f"**{cap_type} Cap**: {format_gold_amount(get_gold_cap(member.id, ctx.guild.id))} gold pieces",
            inline=False
        )

        # Add data persistence notice
        embed.add_field(
            name="💾 Data Persistence",
            value="All thy records are safely preserved in the royal archives!",
            inline=False
        )

        embed.set_thumbnail(url=TREASURY_SEAL_URL)
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! An error hath befallen the exchequer: {str(e)}", success=False))

@bot.command(name="backup")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def backup_cmd(ctx):
    """Create a complete backup of all data (Admin only)"""
    try:
        # Create backup
        backup_file = backup_all_data()

        if backup_file:
            # Export summary
            summary = export_data_summary()

            embed = medieval_embed(
                title="💾 Royal Archive Backup Complete",
                description=f"{get_royal_proclamation()} The royal archives have been preserved for posterity!",
                color_name="green"
            )

            embed.add_field(
                name="📁 Backup File",
                value=f"`{backup_file}`",
                inline=False
            )

            if summary:
                embed.add_field(
                    name="📊 Data Summary",
                    value=f"Active Users: **{summary.get('active_users', 0)}**\n"
                          f"Total Gold: **{format_gold_amount(summary.get('total_gold_circulation', 0))}**\n"
                          f"Config Entries: **{summary.get('persistent_config', 0)}**",
                    inline=True
                )

            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=medieval_response("The backup failed most grievously!", success=False))

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The backup scribes protest: {str(e)}", success=False))

@bot.command(name="datastatus")
@commands.guild_only()
async def data_status_cmd(ctx):
    """Show comprehensive data persistence status"""
    try:
        summary = export_data_summary()

        embed = medieval_embed(
            title="📊 Royal Data Archives Status",
            description="The complete accounting of His Majesty's persistent records:",
            color_name="blue"
        )

        if summary:
            for table, count in summary.items():
                if table not in ['total_gold_circulation', 'active_users']:
                    embed.add_field(
                        name=f"📋 {table.replace('_', ' ').title()}",
                        value=f"**{count}** records",
                        inline=True
                    )

            embed.add_field(
                name="💰 Total Gold in Circulation",
                value=f"**{format_gold_amount(summary.get('total_gold_circulation', 0))}** gold pieces",
                inline=False
            )

            embed.add_field(
                name="👥 Active Citizens",
                value=f"**{summary.get('active_users', 0)}** subjects registered",
                inline=True
            )

        embed.add_field(
            name="💾 Persistence Level",
            value="**MAXIMUM** - All data permanently preserved",
            inline=False
        )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The record keepers are confounded: {str(e)}", success=False))

@bot.command(name="adminbounty")
@commands.guild_only()
async def admin_bounty_cmd(ctx):
    """Claim thy monthly administrator's bounty (30 billion gold)"""
    try:
        success, amount, error = claim_admin_monthly_bonus(ctx.author.id, ctx.guild.id)

        if success:
            embed = medieval_embed(
                title="👑 Royal Administrator's Bounty",
                description=f"{get_royal_proclamation()} By royal decree, the administrator's monthly bounty is conferred!",
                color_name="green"
            )
            embed.add_field(
                name="💰 Bounty Received",
                value=f"**{format_gold_amount(amount)}** gold pieces from the royal treasury!",
                inline=True
            )
            embed.add_field(
                name="📅 Next Available",
                value="Return in one month's time for thy next bounty!",
                inline=True
            )
            embed.set_image(url=COIN_GIF_URL)
            await ctx.send(embed=embed)
        else:
            embed = medieval_embed(
                title="⏰ Bounty Unavailable",
                description=error or "The royal bounty cannot be claimed at this time!",
                color_name="orange"
            )
            await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The royal exchequer protesteth: {str(e)}", success=False))

@bot.command(name="stipend")
@commands.guild_only()
async def stipend_cmd(ctx):
    """Claim thy daily royal stipend"""
    try:
        success, amount = claim_daily(ctx.author.id, ctx.guild.id)

        if success:
            embed = medieval_embed(
                title="👑 Royal Daily Stipend",
                description=f"{get_royal_proclamation()} {get_daily_stipend_phrase()}",
                color_name="green"
            )
            embed.add_field(
                name="💰 Gold Received",
                value=f"**{amount}** gold pieces from the royal coffers!",
                inline=True
            )
            embed.set_image(url=COIN_GIF_URL)
            await ctx.send(embed=embed)
        else:
            embed = medieval_embed(
                title="⏰ Stipend Already Claimed",
                description="Forsooth! Thou hast already received thy daily stipend!",
                color_name="orange"
            )
            embed.add_field(
                name="🕐 Next Available",
                value="Return anon when the sun hath completed its cycle!",
                inline=False
            )
            await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The exchequer hath failed: {str(e)}", success=False))

@bot.command(name="labour")
@commands.guild_only()
async def labour_cmd(ctx):
    """Perform honest labour for wages - now with 1-hour individual cooldown!"""
    try:
        success, amount, remaining_seconds = work(ctx.author.id, ctx.guild.id)

        if success:
            embed = medieval_embed(
                title="⚒️ Honest Labour",
                description=f"{get_royal_proclamation()} {get_work_phrase()}",
                color_name="green"
            )
            embed.add_field(
                name="💰 Wages Earned",
                value=f"**{amount}** gold pieces for thy toil!",
                inline=True
            )
            embed.set_image(url=ROYAL_CREST)
            await ctx.send(embed=embed)
        else:
            # Show detailed cooldown information
            remaining_time = format_time_remaining(remaining_seconds)
            embed = medieval_embed(
                title="⏰ Labour Cooldown",
                description="Thou must rest ere working again, good master!",
                color_name="orange"
            )
            embed.add_field(
                name="🕐 Time Until Next Labour",
                value=f"**{remaining_time}**",
                inline=False
            )
            embed.add_field(
                name="💡 Tip",
                value="Each citizen hath their own labour schedule - return when rested!",
                inline=False
            )
            await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The guild masters protest: {str(e)}", success=False))

@bot.command(name="wager")
@commands.guild_only()
async def wager_cmd(ctx, amount: int, game: str = "dice"):
    """Wager gold upon games of chance - NOW WITH WEEKLY LIMITS!"""
    try:
        valid_games = ["dice", "coin", "slots"]
        if game not in valid_games:
            return await ctx.send(embed=medieval_response(
                f"Valid games be these: {', '.join(valid_games)}",
                success=False
            ))

        if amount <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must wager a positive sum, good master!",
                success=False
            ))

        # Check weekly gambling tries first
        can_gamble, remaining_tries, used_tries = can_gamble_weekly(ctx.author.id, ctx.guild.id)

        if not can_gamble:
            embed = medieval_embed(
                title="🃏 Weekly Gambling Limit Reached",
                description=f"Forsooth! Thou hast exhausted thy weekly gambling allowance!",
                color_name="red"
            )
            embed.add_field(
                name="📊 Usage This Week",
                value=f"**{used_tries}**/{WEEKLY_GAMBLING_TRIES} tries used",
                inline=True
            )
            embed.add_field(
                name="⏰ Resets",
                value="Monday at midnight UTC",
                inline=True
            )
            await ctx.send(embed=embed)
            return

        win, win_amount, tries_info = gamble(ctx.author.id, ctx.guild.id, amount, game)

        if win_amount == 0 and tries_info.startswith("Thou hast exhausted"):
            await ctx.send(embed=medieval_response(tries_info, success=False))
            return

        if win:
            embed = medieval_embed(
                title=f"🎲 {game.title()} - Victory!",
                description=f"{get_royal_proclamation()} {get_gamble_phrase()}",
                color_name="green"
            )
            embed.add_field(
                name="💰 Gold Won",
                value=f"**{format_gold_amount(win_amount)}** gold pieces from the wager!",
                inline=True
            )
            embed.add_field(
                name="🎯 Net Profit",
                value=f"**{format_gold_amount(win_amount - amount)}** gold pieces!",
                inline=True
            )
            embed.set_image(url="https://media.giphy.com/media/3ohzdYrPBjW6cy2gla/giphy.gif")
        else:
            embed = medieval_embed(
                title=f"🎲 {game.title()} - Defeat",
                description="Fortune was not with thee this day, good master!",
                color_name="red"
            )
            embed.add_field(
                name="💰 Gold Lost",
                value=f"**{format_gold_amount(amount)}** gold pieces to the house!",
                inline=True
            )
            embed.add_field(
                name="😔 Outcome",
                value="Better luck next time, noble friend!",
                inline=True
            )

        # Add weekly gambling status to embed
        if tries_info:
            embed.add_field(
                name="🃏 Weekly Status",
                value=tries_info.strip(),
                inline=False
            )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The gaming tables protest: {str(e)}", success=False))

@bot.command(name="pay")
@commands.guild_only()
async def pay_cmd(ctx, member: discord.Member, amount: int):
    """Pay gold to another subject"""
    try:
        if amount <= 0:
            return await ctx.send(embed=medieval_response(
                "Thy sum must be positive, good master!",
                success=False
            ))

        if member.id == ctx.author.id:
            return await ctx.send(embed=medieval_response(
                "Thou canst not pay thyself, good sir!",
                success=False
            ))

        success, error = transfer_gold(ctx.author.id, member.id, ctx.guild.id, amount)

        if success:
            embed = medieval_embed(
                title="💰 Royal Payment",
                description=f"{get_royal_proclamation()} A transaction hath been completed betwixt subjects!",
                color_name="green"
            )
            embed.add_field(
                name="🧑‍💼 Payer",
                value=f"{ctx.author.mention} the Generous",
                inline=True
            )
            embed.add_field(
                name="👑 Recipient",
                value=f"{member.mention} the Fortunate",
                inline=True
            )
            embed.add_field(
                name="💰 Payment",
                value=f"**{format_gold_amount(amount)}** gold pieces transferred!",
                inline=True
            )

            await ctx.send(embed=embed)

            # Try to DM the recipient
            try:
                dm_embed = medieval_embed(
                    title="💰 Payment Received",
                    description=f"Hail! Thou hast received coin from {ctx.author.display_name}!",
                    color_name="green"
                )
                dm_embed.add_field(
                    name="💰 Amount Received",
                    value=f"**{format_gold_amount(amount)}** gold pieces!",
                    inline=True
                )
                await member.send(embed=dm_embed)
            except:
                pass

        else:
            await ctx.send(embed=medieval_response(error, success=False))

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The transfer failed: {str(e)}", success=False))

@bot.command(name="chronicles")
@commands.guild_only()
async def chronicles_cmd(ctx, member: discord.Member = None):
    """View thy economic chronicles - now with wins/losses!"""
    try:
        member = member or ctx.author
        stats = get_economy_stats(member.id, ctx.guild.id)

        if not stats:
            return await ctx.send(embed=medieval_response(
                "No economic chronicles exist for this subject!",
                success=False
            ))

        # Get real Discord role information
        medieval_title, hierarchy_text, highest_role = get_user_role_info(member)

        # Get weekly gambling status
        can_gamble, remaining_tries, used_tries = can_gamble_weekly(member.id, ctx.guild.id)

        embed = medieval_embed(
            title=f"📊 Royal Chronicles of {member.display_name}",
            description=f"The exchequer's records concerning {member.display_name}, {medieval_title} of the realm:",
            color_name="blue"
        )

        embed.add_field(
            name="💰 Purse Holdings",
            value=f"**{format_gold_amount(stats['gold'])}** gold pieces",
            inline=False
        )

        # WINS/LOSSES TRACKING INSTEAD OF VAULT
        total_games = stats['gamble_wins'] + stats['gamble_losses']
        if total_games > 0:
            win_rate = (stats['gamble_wins'] / total_games) * 100
            embed.add_field(
                name="🎲 Gaming Record",
                value=f"**{stats['gamble_wins']}** victories | **{stats['gamble_losses']}** defeats\n**{win_rate:.1f}%** success rate",
                inline=True
            )

        # WEEKLY GAMBLING STATUS
        embed.add_field(
            name="🃏 Weekly Gambling",
            value=f"**{remaining_tries}**/{WEEKLY_GAMBLING_TRIES} tries remaining this week",
            inline=True
        )

        embed.add_field(
            name="📈 Lifetime Earnings",
            value=f"**{format_gold_amount(stats['total_gold_earned'])}** gold pieces",
            inline=True
        )

        embed.add_field(
            name="📉 Lifetime Expenditures",
            value=f"**{format_gold_amount(stats['total_gold_spent'])}** gold pieces",
            inline=True
        )

        embed.add_field(
            name="⚔️ Discord Station",
            value=f"**{highest_role.name if highest_role else 'Citizen'}** of the Realm",
            inline=False
        )

        # Show role hierarchy information
        if hierarchy_text:
            embed.add_field(
                name="🏰 Role Hierarchy",
                value=hierarchy_text,
                inline=False
            )

        # Show admin status and cap information
        if stats['is_admin']:
            embed.add_field(
                name="👑 Royal Administrator",
                value="Thou art a trusted administrator of the realm!",
                inline=False
            )

        embed.set_thumbnail(url=TREASURY_SEAL_URL)
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The chronicles are lost: {str(e)}", success=False))

@bot.command(name="nobles")
@commands.guild_only()
async def nobles_cmd(ctx):
    """View the realm's most wealthy nobles - NO VAULT"""
    try:
        leaders = get_leaderboard(ctx.guild.id, 10)

        if not leaders:
            return await ctx.send(embed=medieval_response(
                "No wealthy nobles grace our realm!",
                success=True
            ))

        embed = medieval_embed(
            title="🏆 Roll of the Realm's Wealthiest Nobles",
            description="The exchequer's accounting of the realm's most prosperous subjects:",
            color_name="gold"
        )

        for i, row in enumerate(leaders, 1):
            member = ctx.guild.get_member(row['user_id'])
            if member:
                gold_amount = row['gold']  # NO VAULT
                medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"#{i}"

                # Get real role info
                highest_role = get_user_highest_role(member)
                role_info = f" ({highest_role.name})" if highest_role else ""

                # Show admin status
                admin_status = " 👑" if row['is_admin'] else ""

                # Add gaming stats
                total_games = row['gamble_wins'] + row['gamble_losses']
                if total_games > 0:
                    win_rate = (row['gamble_wins'] / total_games) * 100
                    gaming_stats = f"\n🎲 {row['gamble_wins']}W-{row['gamble_losses']}L ({win_rate:.1f}%)"
                else:
                    gaming_stats = ""

                embed.add_field(
                    name=f"{medal} {member.display_name}{role_info}{admin_status}",
                    value=f"**{format_gold_amount(gold_amount)}** gold pieces{gaming_stats}",
                    inline=False
                )

        embed.set_thumbnail(url=TREASURY_SEAL_URL)
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The roll is incomplete: {str(e)}", success=False))

@bot.command(name="wares")
@commands.guild_only()
async def wares_cmd(ctx):
    """View the royal merchant's fine Discord roles"""
    try:
        items = get_shop_items(ctx.guild.id)

        if not items:
            return await ctx.send(embed=medieval_response(
                "The royal shop stands empty! Command thy stewards to stock it with Discord roles.",
                success=True
            ))

        embed = medieval_embed(
            title="🏪 Royal Merchant's Fine Discord Roles",
            description="Discord roles available for purchase in His Majesty's shop:",
            color_name="purple"
        )

        for item in items:
            stock_text = f"Stock: {item['stock']}" if item['stock'] > 0 else "Unlimited"

            # Show role information
            role_info = ""
            if item['role_name']:
                role_color = f" (Color: {item['role_color']})" if item['role_color'] else ""
                role_info = f"\nGrants role: **{item['role_name']}**{role_color}"
                if item['role_position'] > 0:
                    role_info += f"\nRole Position: **{item['role_position']}**"

            embed.add_field(
                name=f"{item['name']} - {format_gold_amount(item['price'])} 🪙",
                value=f"{item['description']}\n*{stock_text}*{role_info}",
                inline=False
            )

        embed.add_field(
            name="💡 How to Purchase",
            value=f"Use `{PREFIX}purchase <role_name>` to acquire these fine Discord roles!",
            inline=False
        )

        # Add weekly gambling info
        embed.add_field(
            name="🎲 Weekly Gambling",
            value=f"Each citizen gets **{WEEKLY_GAMBLING_TRIES}** gambling tries per week (resets Monday UTC)",
            inline=False
        )

        embed.set_thumbnail(url=TREASURY_SEAL_URL)
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The shop is in disarray: {str(e)}", success=False))

@bot.command(name="purchase")
@commands.guild_only()
async def purchase_cmd(ctx, *, item_name: str):
    """Purchase Discord role from the royal shop"""
    try:
        items = get_shop_items(ctx.guild.id)

        # Find item by name (case insensitive)
        item_id = None
        for item in items:
            if item['name'].lower() == item_name.lower():
                item_id = item['id']
                break

        if not item_id:
            return await ctx.send(embed=medieval_response(
                f"The ware '{item_name}' exists not in our royal shop!",
                success=False
            ))

        success, item_name, role_mention = await buy_item(ctx.author.id, ctx.guild.id, item_id, ctx.guild)

        if success:
            embed = medieval_embed(
                title="💰 Purchase Complete",
                description=f"{get_royal_proclamation()} Thou hast purchased **{item_name}** from the royal treasury!",
                color_name="green"
            )

            if role_mention:
                embed.add_field(
                    name="⚔️ Discord Role Conferred",
                    value=f"By royal decree, thou art now {role_mention}!",
                    inline=False
                )
                embed.set_thumbnail(url=CHEST_URL)

            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=medieval_response(item_name, success=False))

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The purchase failed: {str(e)}", success=False))

@bot.command(name="treasures")
@commands.guild_only()
async def treasures_cmd(ctx, member: discord.Member = None):
    """View thy purchased Discord roles"""
    try:
        member = member or ctx.author
        items = get_user_inventory(member.id, ctx.guild.id)

        if not items:
            return await ctx.send(embed=medieval_response(
                f"{member.display_name} owns no Discord roles!",
                success=True
            ))

        embed = medieval_embed(
            title=f"🎒 Discord Roles of {member.display_name}",
            description="The Discord roles belonging to {member.display_name}:",
            color_name="blue"
        )

        for item in items:
            role_color_text = f" (Color: {item['role_color']})" if item['role_color'] else ""
            role_position_text = f"\nPosition: **{item['role_position']}**" if item['role_position'] > 0 else ""

            embed.add_field(
                name=item['name'],
                value=f"{item['description']}\nRole: **{item['role_name']}**{role_color_text}{role_position_text}\nAcquired: <t:{int(dt.fromisoformat(item['purchased_at']).timestamp())}:R>",
                inline=False
            )

        embed.set_thumbnail(url=CHEST_URL)
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The treasury records are amiss: {str(e)}", success=False))

# ---------- MEDIEVAL GIVEAWAY PREFIX COMMANDS ----------
@bot.command(name="setagrole")
@commands.has_permissions(manage_roles=True)
@commands.guild_only()
async def setagrole_cmd(ctx, role: discord.Role):
    """Set roles that can host tournaments/giveaways (Admin)"""
    try:
        guild_id = ctx.guild.id

        # Initialize guild roles if not exists
        if guild_id not in GIVEAWAY_ROLES:
            GIVEAWAY_ROLES[guild_id] = []

        # Add role if not already added
        if role.id not in GIVEAWAY_ROLES[guild_id]:
            GIVEAWAY_ROLES[guild_id].append(role.id)

        # Save to database
        save_giveaway_roles_to_db(guild_id, GIVEAWAY_ROLES[guild_id])

        embed = medieval_embed(
            title="⚔️ Tournament Host Role Set",
            description=f"{get_tournament_proclamation()} {role.mention} can now host royal tournaments!",
            color_name="green"
        )

        embed.add_field(
            name="💡 Current Host Roles",
            value=f"Members with these roles may host tournaments:\n" +
                  "\n".join([f"• {ctx.guild.get_role(rid).mention}" for rid in GIVEAWAY_ROLES[guild_id]]),
            inline=False
        )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The herald's decree failed: {str(e)}", success=False))

@bot.command(name="removeagrole")
@commands.has_permissions(manage_roles=True)
@commands.guild_only()
async def removeagrole_cmd(ctx, role: discord.Role):
    """Remove tournament host role (Admin)"""
    try:
        guild_id = ctx.guild.id

        if guild_id in GIVEAWAY_ROLES and role.id in GIVEAWAY_ROLES[guild_id]:
            GIVEAWAY_ROLES[guild_id].remove(role.id)

            # Save to database
            save_giveaway_roles_to_db(guild_id, GIVEAWAY_ROLES[guild_id])

            embed = medieval_embed(
                title="⚔️ Tournament Host Role Removed",
                description=f"{role.mention} can no longer host tournaments.",
                color_name="orange"
            )
        else:
            embed = medieval_embed(
                title="⚔️ Role Not Found",
                description=f"{role.mention} was not set as a tournament host.",
                color_name="red"
            )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The removal failed: {str(e)}", success=False))

@bot.command(name="tournament")
@commands.guild_only()
async def tournament_cmd(ctx, duration_minutes: int, winner_count: int, prize_amount: int, *, prize_name: str):
    """Host a royal tournament with gold prizes"""
    try:
        # Check permission
        if not has_giveaway_permission(ctx.author, ctx.guild.id):
            return await ctx.send(embed=medieval_response(
                "Thou lacketh permission to host tournaments! Seek the steward's blessing.",
                success=False
            ))

        if duration_minutes < 5 or duration_minutes > 1440:  # 5 min to 24 hours
            return await ctx.send(embed=medieval_response(
                "Tournaments must last between 5 minutes and 24 hours!",
                success=False
            ))

        if winner_count < 1 or winner_count > 10:
            return await ctx.send(embed=medieval_response(
                "A tournament must have 1-10 winners!",
                success=False
            ))

        if prize_amount < 1:
            return await ctx.send(embed=medieval_response(
                "The prize must be at least 1 gold piece!",
                success=False
            ))

        # Check host has enough gold (optional - they pay for the prize)
        host_gold, _, _, _, _, is_admin = get_user_balance(ctx.author.id, ctx.guild.id)
        total_prize = prize_amount * winner_count

        if host_gold < total_prize:
            return await ctx.send(embed=medieval_response(
                f"Thou needst {format_gold_amount(total_prize)} gold to fund this tournament! Thy purse contains only {format_gold_amount(host_gold)}.",
                success=False
            ))

        end_time = utcnow() + timedelta(minutes=duration_minutes)

        embed = medieval_embed(
            title=f"⚔️ Royal Tournament: {prize_name}",
            description=f"{get_tournament_proclamation()} {get_tournament_phrase()}",
            color_name="gold"
        )

        embed.add_field(
            name="🏆 Prize",
            value=f"**{format_gold_amount(prize_amount)}** gold pieces each",
            inline=True
        )

        embed.add_field(
            name="👑 Winners",
            value=f"**{winner_count}** champion(s) will be crowned",
            inline=True
        )

        embed.add_field(
            name="⏰ Duration",
            value=f"Ends <t:{int(end_time.timestamp())}:R>",
            inline=True
        )

        embed.add_field(
            name="🎭 Tournament Host",
            value=f"{ctx.author.mention} the Generous",
            inline=False
        )

        embed.add_field(
            name="💡 How to Enter",
            value="React with ⚔️ to join the tournament!",
            inline=False
        )

        embed.set_thumbnail(url=TOURNAMENT_URL)

        message = await ctx.send(embed=embed)
        await message.add_reaction("⚔️")

        # Create giveaway in database
        success = create_giveaway(
            ctx.guild.id, ctx.channel.id, message.id, ctx.author.id,
            prize_name, prize_amount, end_time, winner_count
        )

        if success:
            # Deduct gold from host
            update_user_balance(ctx.author.id, ctx.guild.id, -total_prize, f"Funded tournament: {prize_name}")

            # Schedule end
            bot.loop.create_task(end_tournament_later(message.id, duration_minutes * 60))

        else:
            await ctx.send(embed=medieval_response("The tournament creation failed!", success=False))

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The herald's trumpet failed: {str(e)}", success=False))

async def end_tournament_later(message_id, delay_seconds):
    """End tournament after delay"""
    await asyncio.sleep(delay_seconds)

    try:
        with get_db_connection() as db:
            giveaway = db.execute("""
            SELECT * FROM active_giveaways
            WHERE message_id=? AND status='active'
            """, (message_id,)).fetchone()

            if giveaway:
                await end_tournament(giveaway['id'])

    except Exception as e:
        print(f"Error ending tournament: {e}")

async def end_tournament(giveaway_id):
    """End a tournament and announce winners"""
    try:
        winners, giveaway = end_giveaway(giveaway_id)

        if not giveaway:
            return

        guild = bot.get_guild(giveaway['guild_id'])
        if not guild:
            return

        channel = guild.get_channel(giveaway['channel_id'])
        if not channel:
            return

        if winners:
            winner_mentions = [guild.get_member(winner_id).mention for winner_id in winners if guild.get_member(winner_id)]

            embed = medieval_embed(
                title=f"🏆 Tournament Concluded: {giveaway['prize_name']}",
                description=f"{get_tournament_proclamation()} The champions have been chosen by fortune!",
                color_name="gold"
            )

            embed.add_field(
                name="👑 Champions",
                value="\n".join(winner_mentions),
                inline=False
            )

            embed.add_field(
                name="💰 Prize",
                value=f"Each champion receives **{format_gold_amount(giveaway['prize_amount'])}** gold pieces!",
                inline=False
            )

            embed.set_thumbnail(url=CHEST_URL)

            await channel.send(embed=embed)

            # DM winners
            for winner_id in winners:
                winner = guild.get_member(winner_id)
                if winner:
                    try:
                        dm_embed = medieval_embed(
                            title="🏆 Tournament Victory!",
                            description=f"Hail, champion! Thou hast won the tournament: **{giveaway['prize_name']}**!",
                            color_name="green"
                        )
                        dm_embed.add_field(
                            name="💰 Prize",
                            value=f"**{format_gold_amount(giveaway['prize_amount'])}** gold pieces have been added to thy purse!",
                            inline=True
                        )
                        await winner.send(embed=dm_embed)
                    except:
                        pass

        else:
            embed = medieval_embed(
                title=f"⚔️ Tournament Ended: {giveaway['prize_name']}",
                description="Alack! No brave souls entered this tournament!",
                color_name="red"
            )
            await channel.send(embed=embed)

    except Exception as e:
        print(f"Error ending tournament: {e}")

@bot.command(name="tournaments")
@commands.guild_only()
async def tournaments_cmd(ctx):
    """View active tournaments in the realm"""
    try:
        active_tournaments = get_active_giveaways(ctx.guild.id)

        if not active_tournaments:
            return await ctx.send(embed=medieval_response(
                "No tournaments are currently proclaimed in the realm!",
                success=True
            ))

        embed = medieval_embed(
            title="⚔️ Active Royal Tournaments",
            description="These tournaments await brave champions:",
            color_name="blue"
        )

        for tournament in active_tournaments:
            host = ctx.guild.get_member(tournament['host_id'])
            channel = ctx.guild.get_channel(tournament['channel_id'])

            end_time = dt.fromisoformat(tournament['end_time'])

            embed.add_field(
                name=f"🏆 {tournament['prize_name']}",
                value=f"Host: {host.mention if host else 'Unknown'}\n"
                      f"Prize: **{format_gold_amount(tournament['prize_amount'])}** gold each\n"
                      f"Winners: **{tournament['winner_count']}**\n"
                      f"Ends: <t:{int(end_time.timestamp())}:R>\n"
                      f"Location: {channel.mention if channel else 'Unknown'}",
                inline=False
            )

        embed.set_thumbnail(url=TOURNAMENT_URL)
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The tournament ledger is amiss: {str(e)}", success=False))

@bot.command(name="addware")
@commands.has_permissions(manage_roles=True)
@commands.guild_only()
async def addware_cmd(ctx, name: str, role: discord.Role, price: int, stock: int = -1, *, description: str):
    """Add Discord role to the royal shop (Admin)"""
    try:
        if price <= 0:
            return await ctx.send(embed=medieval_response(
                "The price must be a positive sum, good master!",
                success=False
            ))

        success = add_shop_item(ctx.guild.id, name, description, price, role, stock, ctx.author.id)

        if success:
            embed = medieval_embed(
                title="🏪 Royal Ware Added",
                description=f"{get_royal_proclamation()} **{name}** hath been added to His Majesty's royal shop!",
                color_name="green"
            )
            embed.add_field(name="💰 Price", value=f"{format_gold_amount(price)} gold pieces", inline=True)
            embed.add_field(name="⚔️ Role Conferred", value=role.mention, inline=True)
            embed.add_field(name="📦 Stock", value=f"{stock if stock > 0 else 'Unlimited'}", inline=True)
            embed.add_field(name="📜 Description", value=description, inline=False)
            embed.add_field(
                name="💡 Usage",
                value=f"Subjects may acquire this role with `{PREFIX}purchase {name}`",
                inline=False
            )

            await ctx.send(embed=embed)
            print(f"✅ Added Discord role '{name}' to royal shop in {ctx.guild.name}")

        else:
            await ctx.send(embed=medieval_response("The addition failed most grievously!", success=False))

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The royal shopkeepers protest: {str(e)}", success=False))

@bot.command(name="removeware")
@commands.has_permissions(manage_roles=True)
@commands.guild_only()
async def removeware_cmd(ctx, *, name: str):
    """Remove ware from the royal shop (Admin)"""
    try:
        with get_db_connection() as db:
            result = db.execute("""
            DELETE FROM shop_items
            WHERE guild_id=? AND name=?
            """, (ctx.guild.id, name))

            if result.rowcount > 0:
                db.commit()
                await ctx.send(embed=medieval_response(
                    f"**{name}** hath been removed from His Majesty's shop!",
                    success=True
                ))
            else:
                await ctx.send(embed=medieval_response(
                    f"The ware '{name}' exists not in our royal inventory!",
                    success=False
                ))

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Zounds! The removal failed: {str(e)}", success=False))

# ---------- SLASH COMMANDS (/) - ALL FEATURES ----------
@tree.command(name="purse", description="Inspect thy purse and treasury with wins/losses!")
@app_commands.describe(member="Which subject to inspect (optional)")
async def slash_purse(interaction: discord.Interaction, member: discord.Member = None):
    """Slash command for purse inspection"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        # Create a mock context
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await purse_cmd(ctx, member)

@tree.command(name="stipend", description="Claim thy daily royal stipend (3-7 gold)")
async def slash_stipend(interaction: discord.Interaction):
    """Slash command for daily stipend"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await stipend_cmd(ctx)

@tree.command(name="labour", description="Perform honest labour for wages (8-15 gold, 1-hour cooldown)")
async def slash_labour(interaction: discord.Interaction):
    """Slash command for labour"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await labour_cmd(ctx)

@tree.command(name="wager", description="Wager gold upon games of chance")
@app_commands.describe(
    amount="How much gold to wager",
    game="Which game to play (dice/coin/slots)"
)
@app_commands.choices(game=[
    app_commands.Choice(name="Dice (50% win)", value="dice"),
    app_commands.Choice(name="Coin Flip (48% win)", value="coin"),
    app_commands.Choice(name="Slots (up to 10x)", value="slots")
])
async def slash_wager(interaction: discord.Interaction, amount: int, game: str = "dice"):
    """Slash command for gambling"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await wager_cmd(ctx, amount, game)

@tree.command(name="pay", description="Pay gold to another subject")
@app_commands.describe(
    member="Who to pay",
    amount="How much gold to transfer"
)
async def slash_pay(interaction: discord.Interaction, member: discord.Member, amount: int):
    """Slash command for paying"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await pay_cmd(ctx, member, amount)

@tree.command(name="chronicles", description="View economic chronicles with wins/losses")
@app_commands.describe(member="Which subject to inspect (optional)")
async def slash_chronicles(interaction: discord.Interaction, member: discord.Member = None):
    """Slash command for chronicles"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await chronicles_cmd(ctx, member)

@tree.command(name="nobles", description="View the realm's wealthiest nobles")
async def slash_nobles(interaction: discord.Interaction):
    """Slash command for nobles"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await nobles_cmd(ctx)

@tree.command(name="wares", description="View Discord roles for purchase in the royal shop")
async def slash_wares(interaction: discord.Interaction):
    """Slash command for wares"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await wares_cmd(ctx)

@tree.command(name="purchase", description="Purchase Discord role from the royal shop")
@app_commands.describe(item_name="Name of the role to purchase")
async def slash_purchase(interaction: discord.Interaction, item_name: str):
    """Slash command for purchase"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await purchase_cmd(ctx, item_name=item_name)

@tree.command(name="treasures", description="View thy purchased Discord roles")
@app_commands.describe(member="Which subject to inspect (optional)")
async def slash_treasures(interaction: discord.Interaction, member: discord.Member = None):
    """Slash command for treasures"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await treasures_cmd(ctx, member)

@tree.command(name="adminbounty", description="Claim thy monthly administrator's bounty (30 billion gold)")
async def slash_adminbounty(interaction: discord.Interaction):
    """Slash command for admin bounty"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await admin_bounty_cmd(ctx)

@tree.command(name="datastatus", description="Show comprehensive data persistence status")
async def slash_datastatus(interaction: discord.Interaction):
    """Slash command for data status"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await data_status_cmd(ctx)

@tree.command(name="charter", description="Display the complete royal charter of commands")
async def slash_charter(interaction: discord.Interaction):
    """Slash command for charter"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await charter_cmd(ctx)

# ---------- SLASH ADMIN COMMANDS ----------
@tree.command(name="setagrole", description="Set roles that can host tournaments (Admin)")
@app_commands.describe(role="Role that can host tournaments")
@app_commands.default_permissions(manage_roles=True)
async def slash_setagrole(interaction: discord.Interaction, role: discord.Role):
    """Slash command for setagrole"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await setagrole_cmd(ctx, role)

@tree.command(name="removeagrole", description="Remove tournament host role (Admin)")
@app_commands.describe(role="Role to remove from tournament hosts")
@app_commands.default_permissions(manage_roles=True)
async def slash_removeagrole(interaction: discord.Interaction, role: discord.Role):
    """Slash command for removeagrole"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await removeagrole_cmd(ctx, role)

@tree.command(name="tournament", description="Host a royal tournament with gold prizes")
@app_commands.describe(
    duration_minutes="How long the tournament lasts (5-1440 minutes)",
    winner_count="How many winners (1-10)",
    prize_amount="Gold prize for each winner",
    prize_name="Name of the tournament prize"
)
async def slash_tournament(interaction: discord.Interaction, duration_minutes: int, winner_count: int, prize_amount: int, prize_name: str):
    """Slash command for tournament"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await tournament_cmd(ctx, duration_minutes, winner_count, prize_amount, prize_name)

@tree.command(name="tournaments", description="View active tournaments in the realm")
async def slash_tournaments(interaction: discord.Interaction):
    """Slash command for tournaments"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await tournaments_cmd(ctx)

@tree.command(name="addware", description="Add Discord role to the royal shop (Admin)")
@app_commands.describe(
    name="Name of the ware",
    role="Discord role to grant",
    price="Price in gold pieces",
    stock="Stock quantity (-1 for unlimited)",
    description="Description of the ware"
)
@app_commands.default_permissions(manage_roles=True)
async def slash_addware(interaction: discord.Interaction, name: str, role: discord.Role, price: int, stock: int = -1, description: str = "A fine Discord role from the royal shop"):
    """Slash command for addware"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await addware_cmd(ctx, name, role, price, stock, description)

@tree.command(name="removeware", description="Remove ware from the royal shop (Admin)")
@app_commands.describe(name="Name of the ware to remove")
@app_commands.default_permissions(manage_roles=True)
async def slash_removeware(interaction: discord.Interaction, name: str):
    """Slash command for removeware"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await removeware_cmd(ctx, name=name)

@tree.command(name="backup", description="Create a complete backup of all data (Admin)")
@app_commands.default_permissions(administrator=True)
async def slash_backup(interaction: discord.Interaction):
    """Slash command for backup"""
    await interaction.response.defer()
    ctx = await bot.get_context(interaction.message) if interaction.message else None
    if not ctx:
        class MockContext:
            def __init__(self, interaction):
                self.author = interaction.user
                self.guild = interaction.guild
                self.send = interaction.followup.send
        ctx = MockContext(interaction)
    
    await backup_cmd(ctx)

# ---------- REACTION HANDLER FOR TOURNAMENTS ----------
@bot.event
async def on_reaction_add(reaction, user):
    """Handle tournament entries via reactions"""
    if user.bot:
        return

    if reaction.emoji == "⚔️":
        try:
            with get_db_connection() as db:
                giveaway = db.execute("""
                SELECT * FROM active_giveaways
                WHERE message_id=? AND status='active'
                """, (reaction.message.id,)).fetchone()

                if giveaway:
                    success, message = enter_giveaway(giveaway['id'], user.id)
                    if success:
                        try:
                            embed = medieval_embed(
                                title="⚔️ Tournament Entry Confirmed",
                                description=f"Hail, {user.mention}! Thou hast entered the tournament: **{giveaway['prize_name']}**!",
                                color_name="green"
                            )
                            await user.send(embed=embed)
                        except:
                            pass

        except Exception as e:
            print(f"Error handling reaction: {e}")

# ---------- COMPREHENSIVE MEDIEVAL HELP SYSTEM ----------
class MedievalHelpView(discord.ui.View):
    def __init__(self, embeds, timeout=120.0):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.embeds) - 1

    @discord.ui.button(label="⬅️ Previous Chronicle", style=discord.ButtonStyle.blurple)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="➡️ Next Chronicle", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="🗑️ Close Ledger", style=discord.ButtonStyle.red)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

@bot.command(name="charter")
@commands.guild_only()
async def charter_cmd(ctx):
    """Display the complete royal charter of commands"""
    try:
        # Create comprehensive help pages
        help_pages = []

        # Page 1 - Basic Economy
        page1 = medieval_embed(
            title="📜 Royal Charter - Page I: Basic Economy",
            description=f"{get_royal_proclamation()} The complete guide to His Majesty's ULTIMATE economic system:",
            color_name="gold"
        )

        page1.add_field(
            name="💰 Essential Commands",
            value=f"**Prefix**: `{PREFIX}command` **Slash**: `/command`\n"
                  f"`{PREFIX}purse` `/purse` - Inspect thy purse and treasury\n"
                  f"`{PREFIX}stipend` `/stipend` - Claim thy daily royal stipend (3-7 gold)\n"
                  f"`{PREFIX}labour` `/labour` - Perform honest labour for wages (8-15 gold)\n"
                  f"`{PREFIX}pay` `/pay` - Pay gold to another subject",
            inline=False
        )

        page1.add_field(
            name="📊 Records & Statistics",
            value=f"`{PREFIX}chronicles` `/chronicles` - View economic chronicles\n"
                  f"`{PREFIX}nobles` `/nobles` - See the realm's wealthiest nobles\n"
                  f"`{PREFIX}datastatus` `/datastatus` - View comprehensive data persistence status",
            inline=False
        )

        page1.add_field(
            name="⚔️ Enhanced Features",
            value="• **1-Hour Labour Cooldown**: Each citizen hath their own work schedule\n"
                  "• **Wins/Losses Tracking**: Gaming record displayed in purse\n"
                  "• **Weekly Gambling**: 30 tries per week (resets Monday UTC)\n"
                  "• **NO Vault System**: All gold kept in purse for simplicity\n"
                  "• **Real Discord Roles**: Purchase actual Discord roles with gold\n"
                  "• **Complete Data Persistence**: Everything saved to database\n"
                  "• **Dual Command System**: Use both prefix (`!`) and slash (`/`) commands!",
            inline=False
        )

        help_pages.append(page1)

        # Page 2 - Gambling & Games
        page2 = medieval_embed(
            title="📜 Royal Charter - Page II: Gaming & Wagering",
            description=f"{get_royal_proclamation()} Try thy luck at His Majesty's gaming tables:",
            color_name="purple"
        )

        page2.add_field(
            name="🎲 Games of Chance",
            value=f"`{PREFIX}wager` `/wager` - Wager gold upon games\n"
                  f"• **Dice**: Cast the bones (50% to double)\n"
                  f"• **Coin**: Flip the royal coin (48% to double)\n"
                  f"• **Slots**: Turn the wheel of fortune (up to 10x payout)",
            inline=False
        )

        page2.add_field(
            name="💡 Gaming Wisdom",
            value=f"• **Weekly Limit**: {WEEKLY_GAMBLING_TRIES} gambling tries per week\n"
                  "• Wins and losses tracked in thy purse\n"
                  "• Dice offer fairest odds to brave souls\n"
                  "• Slots provide greatest rewards but rarest victories\n"
                  "• Weekly counter resets every Monday at midnight UTC\n"
                  "• Use either `!wager` or `/wager` to play!",
            inline=False
        )

        help_pages.append(page2)

        # Page 3 - Discord Role Shop
        page3 = medieval_embed(
            title="📜 Royal Charter - Page III: Discord Role Shop",
            description=f"{get_royal_proclamation()} Acquire real Discord roles with gold:",
            color_name="blue"
        )

        page3.add_field(
            name="🏪 Discord Role Commerce",
            value=f"`{PREFIX}wares` `/wares` - View His Majesty's Discord roles\n"
                  f"`{PREFIX}purchase` `/purchase` - Acquire Discord roles\n"
                  f"`{PREFIX}treasures` `/treasures` - View purchased Discord roles",
            inline=False
        )

        page3.add_field(
            name="⚔️ Labour System",
            value="• **1-Hour Personal Cooldown**: Each person hath their own schedule\n"
                  "• **Personal Timer**: No global cooldown - individual tracking\n"
                  "• **Detailed Reminders**: Shows exact time until next work\n"
                  "• **Dual Commands**: `!labour` or `/labour` both work!",
            inline=False
        )

        page3.add_field(
            name="💡 Enhanced Features",
            value="• **Gold Caps**: Administrators have higher treasury limits\n"
                  "• **Admin Bounty**: Monthly 30 billion gold bonus for administrators\n"
                  "• **Wealth Limits**: Normal subjects capped at 50 billion gold\n"
                  "• **Complete Persistence**: All data saved to database\n"
                  "• **Full Compatibility**: All commands work with both systems!",
            inline=False
        )

        help_pages.append(page3)

        # Page 4 - Tournaments & Giveaways
        page4 = medieval_embed(
            title="📜 Royal Charter - Page IV: Tournaments & Giveaways",
            description=f"{get_tournament_proclamation()} Host and participate in royal tournaments:",
            color_name="orange"
        )

        page4.add_field(
            name="⚔️ Tournament Commands",
            value=f"`{PREFIX}tournament` `/tournament` - Host a tournament\n"
                  f"`{PREFIX}tournaments` `/tournaments` - View active tournaments\n"
                  "React with ⚔️ on tournament posts to enter!",
            inline=False
        )

        page4.add_field(
            name="👑 Tournament Management (Admin)",
            value=f"`{PREFIX}setagrole` `/setagrole` - Set who can host tournaments\n"
                  f"`{PREFIX}removeagrole` `/removeagrole` - Remove tournament host role\n"
                  f"`{PREFIX}backup` `/backup` - Create complete data backup",
            inline=False
        )

        page4.add_field(
            name="💡 Tournament Wisdom",
            value="• Only designated hosts may create tournaments\n"
                  "• Tournaments require gold funding from the host\n"
                  "• Winners are chosen randomly from entrants\n"
                  "• React with ⚔️ to enter any tournament\n"
                  "• All data persistently saved to database\n"
                  "• Use either prefix or slash commands!",
            inline=False
        )

        help_pages.append(page4)

        # Page 5 - Admin Commands
        page5 = medieval_embed(
            title="📜 Royal Charter - Page V: Steward Commands",
            description=f"{get_royal_proclamation()} For His Majesty's trusted stewards only:",
            color_name="red"
        )

        page5.add_field(
            name="🏪 Discord Role Shop Management",
            value=f"`{PREFIX}addware` `/addware` - Add Discord role\n"
                  f"`{PREFIX}removeware` `/removeware` - Remove role from shop",
            inline=False
        )

        page5.add_field(
            name="👑 Administrator Privileges",
            value=f"`{PREFIX}adminbounty` `/adminbounty` - Claim monthly 30 billion gold bonus\n"
                  "• **Higher Gold Cap**: Administrators can hold 100 billion gold\n"
                  "• **Monthly Bounty**: Exclusive 30 billion gold bonus every 30 days\n"
                  "• **Dual Commands**: All admin commands work both ways!",
            inline=False
        )

        page5.add_field(
            name="⚔️ Permission Requirements",
            value="• Requires `Manage Roles` permission\n"
                  "• Administrator Discord permissions for monthly bounty\n"
                  "• Cannot add roles above thine own station\n"
                  "• All transactions are logged by the crown\n"
                  "• Complete data persistence ensures nothing is lost\n"
                  "• Full prefix and slash command support!",
            inline=False
        )

        help_pages.append(page5)

        # Page 6 - Tips & Strategy
        page6 = medieval_embed(
            title="📜 Royal Charter - Page VI: Wisdom & Strategy",
            description=f"{get_royal_proclamation()} Sage advice for prosperity:",
            color_name="teal"
        )

        page6.add_field(
            name="💰 Wealth Building",
            value="• Claim thy daily stipend each day (3-7 gold)\n"
                  "• Work hourly for steady wages (8-15 gold)\n"
                  "• Administrators claim monthly 30 billion bonus\n"
                  "• Purchase Discord roles for prestige and status\n"
                  "• All progress saved permanently to database\n"
                  "• Use `!` or `/` commands - thy choice!",
            inline=False
        )

        page6.add_field(
            name="🎲 Gaming Strategy",
            value=f"• **Weekly Limit**: {WEEKLY_GAMBLING_TRIES} gambling tries per week\n"
                  "• Track wins/losses in thy purse command\n"
                  "• Dice offer the fairest odds (50% win rate)\n"
                  "• Coin flips have slight house edge (48% win rate)\n"
                  "• Slots provide rare but great rewards (up to 10x)\n"
                  "• All gambling data persistently tracked\n"
                  "• Both `!wager` and `/wager` work perfectly!",
            inline=False
        )

        page6.add_field(
            name="⚔️ Enhanced User Experience",
            value="• **1-Hour Personal Cooldown**: Each citizen works at their own pace\n"
                  "• **Wins/Losses Tracking**: Monitor thy gaming success in purse\n"
                  "• **Weekly Gambling Counter**: Know thy remaining tries\n"
                  "• **Real Discord Integration**: Purchase actual server roles\n"
                  "• **Complete Data Persistence**: Never lose progress\n"
                  "• **Dual Command System**: Prefix (`!`) and Slash (`/`) both work!",
            inline=False
        )

        page6.add_field(
            name="🏰 Gold Management",
            value="• **Normal Subjects**: Maximum 50 billion gold pieces\n"
                  "• **Royal Administrators**: Maximum 100 billion gold pieces\n"
                  "• All earnings are capped at these royal limits\n"
                  "• Monthly administrator bonus helps reach higher caps\n"
                  "• All caps and balances persistently saved\n"
                  "• Commands work identically with both systems!",
            inline=False
        )

        page6.add_field(
            name="📜 Final Wisdom",
            value="• All commands integrate with Discord's real role system\n"
                  "• Gold caps prevent inflation in His Majesty's realm\n"
                  "• Administrator privileges grant significant advantages\n"
                  "• Complete data persistence ensures nothing is ever lost\n"
                  "• **DUAL COMMAND SYSTEM**: Prefix (`{PREFIX}`) AND Slash (`/`) commands work!\n"
                  "• May fortune favor thee in His Majesty's eternal realm!",
            inline=False
        )

        help_pages.append(page6)

        # Send with pagination
        view = MedievalHelpView(help_pages)
        await ctx.send(embed=help_pages[0], view=view)

    except Exception as e:
        await ctx.send(embed=medieval_response(f"Alack! The royal charter is incomplete: {str(e)}", success=False))

# ---------- TRADITIONAL HELP ALIASES ----------
@bot.command(name="help")
@commands.guild_only()
async def help_cmd(ctx):
    """Display help (medieval charter)"""
    await charter_cmd(ctx)

@bot.command(name="h")
@commands.guild_only()
async def h_cmd(ctx):
    """Display help (short command)"""
    await charter_cmd(ctx)

@bot.command(name="ehelp")
@commands.guild_only()
async def ehelp_cmd(ctx):
    """Display economy help (medieval charter)"""
    await charter_cmd(ctx)

# ---------- ON READY ----------
@bot.event
async def on_ready():
    try:
        print(f'🏰 ULTIMATE MERGED Medieval Economy Bot hath awakened as {bot.user}')
        print('⚔️ COMPLETE Royal Treasury system activated!')
        print('🎲 Medieval gaming tables prepared!')
        print('🏪 Real Discord Role shop fully stocked!')
        print('⚔️ Tournament system activated!')
        print('📜 Complete charter of commands loaded!')
        print('💰 Authentic Middle English language engaged!')
        print('👑 Bot ready for COMPLETE PERSISTENCE!')
        print('🏆 Tournament hosting system ready!')
        print('💎 Gold caps system activated!')
        print('👑 Admin monthly bounty system ready!')
        print('🏰 Real Discord role hierarchy system ready!')
        print('⏰ 1-Hour individual labour cooldown system ready!')
        print('📊 Wins/Losses tracking system ready!')
        print('🎲 Weekly gambling tries system activated!')
        print('💾 MAXIMUM DATA PERSISTENCE ACTIVATED!')
        print('🎯 ULTIMATE MERGED VERSION READY!')
        print('🔄 DUAL COMMAND SYSTEM: BOTH PREFIX AND SLASH COMMANDS WORK!')

        # Create initial backup
        backup_all_data()
        export_data_summary()

        # Sync slash commands
        try:
            synced = await tree.sync()
            print(f"✅ Synced {len(synced)} slash commands")
        except Exception as e:
            print(f"❌ Failed to sync slash commands: {e}")

    except Exception as e:
        print(f"Error in on_ready: {e}")

# ---------- AUTHENTIC MEDIEVAL ERROR HANDLER ----------
@bot.event
async def on_command_error(ctx, error):
    """Handle errors with medieval flair"""
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=medieval_response(
            "Thou lacketh the royal permissions for this action!",
            success=False
        ))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=medieval_response(
            f"Thou hast forgotten the '{error.param.name}', good master!",
            success=False
        ))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=medieval_response(
            f"Thy argument is most flawed: {str(error)}",
            success=False
        ))
    else:
        print(f"Command error: {error}")
        await ctx.send(embed=medieval_response(
            "An ill omen hath befallen the royal clerks!",
            success=False
        ))

# ---------- RUN ----------
app = flask.Flask(__name__)

@app.route('/')
def home():
    return "Medieval Economy Bot is alive! 🏰 Royal Treasury & Tournaments running."

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

if __name__ == "__main__":
    try:
        init_db()
        print("🏰 Initializing ULTIMATE MERGED Medieval Economy Bot...")
        print("⚔️ COMPLETE Royal exchequer established!")
        print("🎲 Gaming tables prepared!")
        print("🏪 Real Discord Role shop opened!")
        print("⚔️ Tournament grounds prepared!")
        print("📜 Medieval charter inscribed!")
        print("💰 Authentic Middle English engaged!")
        print("👑 Medieval economy ready for commerce!")
        print("🏆 Tournament system activated!")
        print("💎 Gold caps system activated!")
        print("👑 Admin monthly bounty system ready!")
        print("🏰 Real Discord role hierarchy system ready!")
        print("⏰ 1-Hour individual labour cooldown system ready!")
        print("📊 Wins/Losses tracking system ready!")
        print("🎲 Weekly gambling tries system ready!")
        print("💾 MAXIMUM DATA PERSISTENCE ACHIEVED!")
        print("🎯 ALL SYSTEMS PERSISTENT - ULTIMATE MERGED VERSION!")
        print("🔄 DUAL COMMAND SYSTEM: PREFIX AND SLASH COMMANDS BOTH WORK!")

        # Start Flask keep-alive server in background thread
        Thread(target=run_flask, daemon=True).start()

        # Start the Discord bot
        bot.run(TOKEN)
    except Exception as e:
        print(f"Failed to start medieval economy bot: {e}")
        traceback.print_exc()
