from calculate_num import convert_to_int
import logging
import sqlite3 as sql
from os import getenv

import nextcord as nc
import requests
from dotenv import load_dotenv
from nextcord.ext import application_checks as nc_app_checks
from nextcord.ext import commands as nc_cmd

# Find a load a .env file
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nextcord")


def _require_env(key: str) -> str:
    value = getenv(key)
    if value is None:
        raise RuntimeError(f"Required environment variable {key!r} is not set")
    return value


DB_FILE: str = _require_env("DB_FILE")
GUILD_ID: int = int(_require_env("GUILD_ID"))
MENTOR_ROLE_ID: int = int(_require_env("MENTOR_ROLE_ID"))
ORGANIZER_ROLE_ID: int = int(_require_env("ORGANIZER_ROLE_ID"))
MENTOR_CHANNEL_ID: int = int(_require_env("MENTOR_CHANNEL_ID"))
HELP_CHANNEL_ID: int = int(_require_env("HELP_CHANNEL_ID"))
WELCOME_MESSAGE_ID: int = int(_require_env("WELCOME_MESSAGE_ID"))
ANNOUNCEMENT_CHANNEL_ID: int = int(_require_env("ANNOUNCEMENT_CHANNEL_ID"))
ANNOUNCEMENT_ENDPOINT: str = _require_env("ANNOUNCEMENT_ENDPOINT")
ANNOUNCEMENT_SECRET: str = _require_env("ANNOUNCEMENT_SECRET")
COUNTING_CHANNEL_ID: int = int(_require_env("COUNTING_CHANNEL_ID"))
API_TOKEN: str = _require_env("API_TOKEN")
COUNTING_START: int = int(getenv("COUNTING_START", "0"))


intents: nc.Intents = nc.Intents.default()
intents.message_content = True
bot: nc_cmd.Bot = nc_cmd.Bot(intents=intents)

db_connection: sql.Connection = sql.connect(DB_FILE)

@bot.event
async def on_ready() -> None:
    logging.info(f"We have logged in as {bot.user}")


@bot.event
async def on_application_command_error(ctx: nc.Interaction, err: Exception) -> None:
    if ctx.user is None or ctx.application_command is None:
        return

    user_name = ctx.user.nick if isinstance(ctx.user, nc.Member) and ctx.user.nick else ctx.user.global_name

    logging.warning(
        f"User {user_name} tried to execute {ctx.application_command.qualified_name} but does not have permission to do so."
    )
    await ctx.send("Looks like you don't have permission to run this command... nice try :smiling_imp:", ephemeral=True)


# close {{{1
@bot.slash_command(description="Close a ticket.", guild_ids=[GUILD_ID])
async def close(ctx: nc.Interaction, ticket_id: int) -> None:
    if not isinstance(ctx.user, nc.Member) or ctx.guild is None:
        return

    with db_connection:
        user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name

        try:
            db_cursor = db_connection.cursor()

            if ctx.user.get_role(MENTOR_ROLE_ID) is None:
                ticket_info_query = db_cursor.execute(
                    "SELECT closed, claimed, mentor_assigned FROM tickets WHERE id = :ticket_id AND author_id = :user_id",
                    {"ticket_id": ticket_id, "user_id": ctx.user.id},
                ).fetchone()

                if ticket_info_query is None:
                    logging.warning(
                        f"User {user_name} tried to close a ticket with ID {ticket_id}, but they do not have ownership over it or it does not exist."
                    )

                    await ctx.send(
                        f"You do not have ownership over a ticket with ID {ticket_id}. Maybe you made a typo?",
                        ephemeral=True,
                    )

                    return

                closed, claimed, assignee = ticket_info_query

                if closed == 1:
                    logging.warning(
                        f"User {user_name} tried to close a ticket with ID {ticket_id}, but it is already closed."
                    )

                    await ctx.send("This ticket has already been closed! :star_struck:", ephemeral=True)

                    return

                if claimed == 1:
                    await ctx.send(
                        f"Mentor {assignee} has claimed this ticket. Please contact them to close it.",
                        ephemeral=True,
                    )

                    return

                db_cursor.execute("UPDATE tickets SET closed = 1 WHERE id = :ticket_id", {"ticket_id": ticket_id})

                logging.info(f"User {user_name} closed thier own ticket with ID {ticket_id}.")

                await ctx.send("Ticket closed! :saluting_face:", ephemeral=True)

                return

            ticket_info_query = db_cursor.execute(
                "SELECT closed, mentor_assigned_id, mentor_assigned, claimed, help_thread_id FROM tickets WHERE id = :ticket_id",
                {"ticket_id": ticket_id},
            ).fetchone()

            if ticket_info_query is None:
                await ctx.send(f"A ticket with the ID {ticket_id} does not exist. Please try again.", ephemeral=True)

                logging.warning(f"Mentor {user_name} tried to close non-existant ticket with ID {ticket_id}.")

                return

            closed, ticket_assignee_id, ticket_assignee_name, claimed, help_thread_id = ticket_info_query

            if ctx.user.id != ticket_assignee_id:
                logging.warning(
                    f"Mentor {user_name} tried to close a ticket with ID {ticket_id} owned by {ticket_assignee_name}."
                )

                await ctx.send(
                    f"Woah there! You don't own this ticket... {ticket_assignee_name} does. Contact them to close it.",
                    ephemeral=True,
                )

                return

            if closed == 1:
                logging.warning(
                    f"Mentor {user_name} tried to close a ticket with ID {ticket_id}, but it is already closed."
                )

                await ctx.send("This ticket has already been closed! :star_struck:", ephemeral=True)

                return

            # if the ticket has not been claimed...
            if claimed == 0:
                await ctx.send("This ticket has not been claimed. Please claim it before closing it.", ephemeral=True)

                return

            mentor_channel = await ctx.guild.fetch_channel(MENTOR_CHANNEL_ID)

            if not isinstance(mentor_channel, nc.TextChannel):
                await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)
                return

            help_thread = mentor_channel.get_thread(help_thread_id)

            if help_thread is None:
                logging.error(
                    f"Mentor {user_name} tried to close a ticket with ID {ticket_id}, but help thread could not be found."
                )

                await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)

                return

            await help_thread.delete()
            logging.info(f"Deleted help thread wth ID: {help_thread_id}.")

            db_cursor.execute("UPDATE tickets SET closed = 1 WHERE id = :ticket_id", {"ticket_id": ticket_id})

            db_cursor.execute(
                "UPDATE mentors SET tickets_closed = tickets_closed + 1 WHERE id = :mentor_id",
                {"mentor_id": ctx.user.id},
            )

            logging.info(f"Ticket with ID {ticket_id} has been closed by mentor {user_name}.")
            await ctx.send("Ticket closed!", ephemeral=True)

        except Exception as e:
            logging.error(
                f"Mentor {user_name} tried to close a ticket with ID {ticket_id}, but an unexpected error occured: {e}"
            )

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


# claim {{{1
@bot.slash_command(description="Claim a ticket.", guild_ids=[GUILD_ID])
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)  # type: ignore[arg-type]
@nc_app_checks.has_role(MENTOR_ROLE_ID)
async def claim(ctx: nc.Interaction, ticket_id: int) -> None:
    assert isinstance(ctx.user, nc.Member)
    assert ctx.guild is not None

    with db_connection:
        mentor_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name

        try:
            db_cursor = db_connection.cursor()

            mentor_query = db_cursor.execute(
                "SELECT 1 FROM mentors WHERE id = :mentor_id", {"mentor_id": ctx.user.id}
            ).fetchone()

            # new mentor!
            if mentor_query is None:
                db_cursor.execute(
                    "INSERT INTO mentors (id, name, tickets_claimed, tickets_closed) VALUES (:mentor_id, :mentor_name, 0, 0)",
                    {"mentor_id": ctx.user.id, "mentor_name": mentor_name},
                )

            claim_params = {"ticket_id": ticket_id, "mentor_id": ctx.user.id, "mentor_name": mentor_name}

            ticket_query = db_cursor.execute(
                "SELECT closed, claimed, mentor_assigned, author_id, message, author_location FROM tickets WHERE id = :ticket_id",
                {"ticket_id": ticket_id},
            ).fetchone()

            if ticket_query is None:
                await ctx.send(f"A ticket with the ID {ticket_id} does not exist. Please try again.", ephemeral=True)

                logging.warning(f"Mentor {mentor_name} tried to claim non-existant ticket with ID {ticket_id}.")

                return

            closed, claimed, prev_assignee_name, author_id, ticket_message, author_location = ticket_query

            if closed == 1:
                await ctx.send("This ticket has already been closed! :star_struck:", ephemeral=True)

                return

            # if ticket is already claimed...
            if claimed == 1:
                await ctx.send(
                    f"This ticket has already been claimed by {prev_assignee_name}. Please contact them if you would like to help out.",
                    ephemeral=True,
                )

                return

            ticket_author = await ctx.guild.fetch_member(author_id)

            ticket_author_name = ticket_author.nick if ticket_author.nick else ticket_author.global_name

            help_channel = await ctx.guild.fetch_channel(HELP_CHANNEL_ID)

            if not isinstance(help_channel, nc.TextChannel):
                await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)
                return

            db_cursor.execute(
                "UPDATE tickets SET claimed = 1, mentor_assigned_id = :mentor_id, mentor_assigned = :mentor_name WHERE id = :ticket_id",
                claim_params,
            )

            db_cursor.execute(
                "UPDATE mentors SET tickets_claimed = tickets_claimed + 1 WHERE id = :mentor_id",
                {"mentor_id": ctx.user.id},
            )

            logging.info(f"Mentor {mentor_name} has claimed ticket with ID {ticket_id}.")

            help_thread = await help_channel.create_thread(name=f"Ticket #{ticket_id}", reason=f"Ticket #{ticket_id}")

            logging.info(f"Created help thread with ID {help_thread.id} for ticket with ID {ticket_id}.")

            await help_thread.add_user(ctx.user)
            logging.info(f"Added Mentor {mentor_name} to help thread with ID {help_thread.id}.")

            await help_thread.add_user(ticket_author)
            logging.info(f"Added User {ticket_author_name} to help thread with ID {help_thread.id}.")

            ticket_update_params = {"help_thread_id": help_thread.id, "ticket_id": ticket_id}

            db_cursor.execute(
                "UPDATE tickets SET help_thread_id = :help_thread_id WHERE id = :ticket_id", ticket_update_params
            )

            await ctx.send(f"Ticket #{ticket_id} claimed by {mentor_name}!")

            await help_thread.send(
                f"Greetings {ticket_author.mention}! {ctx.user.mention} is on the way to {author_location} to help you resolve the issue in your ticket:\n> {ticket_message}"
            )

        except Exception as e:
            logging.error(
                f"Mentor {mentor_name} tried to claim a ticket with ID {ticket_id}, but an unexpected error occured: {e}"
            )

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


# helpme {{{1
# guild id just for testing
@bot.slash_command(description="Request help from a mentor.", guild_ids=[GUILD_ID])
# check that message is from a guild and user is a member of said guild. sort of a dumb check, but need for type safety later on.
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)  # type: ignore[arg-type]
async def helpme(ctx: nc.Interaction, author_location: str, ticket_message: str) -> None:
    assert isinstance(ctx.user, nc.Member)
    assert ctx.guild is not None

    with db_connection:
        author_name: str = (
            ctx.user.nick if ctx.user.nick else (ctx.user.global_name or ctx.user.name)
        )  # use guild nickname if available, otherwise use global name

        try:
            db_cursor = db_connection.cursor()

            mentor_channel = await ctx.guild.fetch_channel(MENTOR_CHANNEL_ID)

            if not isinstance(mentor_channel, nc.TextChannel):
                await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)
                return

            ticket_params = {
                "message": ticket_message,
                "author_id": ctx.user.id,
                "author": author_name,
                "author_location": author_location,
                "claimed": False,
                "closed": False,
            }

            db_cursor.execute(
                """
                            INSERT INTO tickets (message, author_id, author, author_location, claimed, closed)
                            VALUES (:message, :author_id, :author, :author_location, :claimed, :closed)
                              """,
                ticket_params,
            )

            logging.info(f"Received ticket from user {ticket_params['author']} with ID {ticket_params['author_id']}.")

            ticket_embed = nc.Embed(
                title="New Ticket Opened! :tickets:",
                description="A hacker needs help. Use `/claim` to claim this ticket!",
            )

            ticket_id = db_cursor.lastrowid

            ticket_embed.add_field(name="__ID__ :hash:", value=str(ticket_id) if ticket_id is not None else "N/A")
            ticket_embed.add_field(name="__Author__ :pen_fountain:", value=author_name)
            ticket_embed.add_field(name="__Location__ :round_pushpin:", value=author_location)
            ticket_embed.add_field(name="__Message__ :scroll:", value=ticket_message, inline=False)

            await mentor_channel.send(embed=ticket_embed)

            await ctx.send(f"Ticket submitted with ID {ticket_id}, help will be on the way soon!", ephemeral=True)

        except Exception as e:
            logging.error(
                f"User {author_name} with ID {ctx.user.id} tried to create a ticket, but an unexpected error occured: {e}"
            )

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


# view all of your tickets. {{{1
@bot.slash_command(description="View all of your tickets.", guild_ids=[GUILD_ID])
# check that message is from a guild and user is a member of said guild. sort of a dumb check, but need for type safety later on.
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)  # type: ignore[arg-type]
async def mytix(ctx: nc.Interaction) -> None:
    assert isinstance(ctx.user, nc.Member)
    assert ctx.guild is not None

    with db_connection:
        try:
            db_cursor = db_connection.cursor()

            # if user is a mentor, treat differently
            if ctx.user.get_role(MENTOR_ROLE_ID) is not None:
                tickets_query = db_cursor.execute(
                    "SELECT id, closed FROM tickets WHERE mentor_assigned_id = :mentor_id", {"mentor_id": ctx.user.id}
                ).fetchall()

                if tickets_query == []:
                    await ctx.send(
                        "You have not claimed any tickets! Use `/opentix` view open tickets to claim.", ephemeral=True
                    )

                    return

                ticket_ids, closeds = zip(*tickets_query)

                closeds = map(lambda x: ":white_check_mark:" if x == 1 else ":no_entry:", closeds)
                ticket_ids = map(str, ticket_ids)

                tickets_embed = nc.Embed(
                    title="Your Claimed Tickets :sunglasses:",
                    description="Use `/status` with the ticket ID for more information on a given ticket.",
                )

                tickets_embed.add_field(name="__ID__ :hash:", value="\n".join(ticket_ids))
                tickets_embed.add_field(name="__Closed__ :tada:", value="\n".join(closeds))

                await ctx.send(embed=tickets_embed, ephemeral=True)

            else:
                # this is an iterable
                tickets_query = db_cursor.execute(
                    "SELECT id, claimed, closed FROM tickets WHERE author_id = :author_id", {"author_id": ctx.user.id}
                ).fetchall()

                if tickets_query == []:
                    await ctx.send("You have no tickets! Use `/helpme` to open one.", ephemeral=True)

                    return

                # get a tuple for each list of fields.
                ticket_ids, claimeds, closeds = zip(*tickets_query)

                # prep the data for embed.
                claimeds = map(lambda x: ":white_check_mark:" if x == 1 else ":no_entry:", claimeds)
                closeds = map(lambda x: ":white_check_mark:" if x == 1 else ":no_entry:", closeds)
                ticket_ids = map(str, ticket_ids)

                tickets_embed = nc.Embed(
                    title="Your Tickets :man_dancing:",
                    description="Use `/status` with the ticket ID for more information on a given ticket.",
                )

                tickets_embed.add_field(name="__ID__ :hash:", value="\n".join(ticket_ids))
                tickets_embed.add_field(name="__Claimed__ :face_with_monocle:", value="\n".join(claimeds))
                tickets_embed.add_field(name="__Closed__ :tada:", value="\n".join(closeds))

                await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:
            user_name = (
                ctx.user.nick if ctx.user.nick else ctx.user.global_name
            )  # use guild nickname if available, otherwise use global name

            logging.error(f"User {user_name} tried to view all of thier tickets, but an unexpected error occured: {e}")

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


# view specific ticket details.{{{1
@bot.slash_command(description="View the details of a specific ticket.", guild_ids=[GUILD_ID])
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)  # type: ignore[arg-type]
async def status(ctx: nc.Interaction, ticket_id: int) -> None:
    assert isinstance(ctx.user, nc.Member)
    assert ctx.guild is not None

    with db_connection:
        db_cursor = db_connection.cursor()

        user_name = (
            ctx.user.nick if ctx.user.nick else ctx.user.global_name
        )  # use guild nickname if available, otherwise use global name

        try:
            # organizer can view all tickets.
            if ctx.user.get_role(ORGANIZER_ROLE_ID) is not None or ctx.user.get_role(MENTOR_ROLE_ID) is not None:
                ticket_query = db_cursor.execute(
                    "SELECT claimed, closed, mentor_assigned, message, author, author_location FROM tickets WHERE id = :ticket_id",
                    {"ticket_id": ticket_id},
                ).fetchone()

            else:
                # mentor or author can access ticket.
                ticket_query = db_cursor.execute(
                    "SELECT claimed, closed, mentor_assigned, message, author, author_location FROM tickets WHERE author_id = :author_id AND id = :ticket_id",
                    {"author_id": ctx.user.id, "ticket_id": ticket_id},
                ).fetchone()

            if ticket_query is None:
                logging.warning(
                    f"User {user_name} tried to view a ticket with ID {ticket_id}, but database query returned nothing."
                )

                await ctx.send(
                    f"You don't have ownership over a ticket with ID {ticket_id}. Maybe you made a typo?",
                    ephemeral=True,
                )

                return

            claimed, closed, mentor, message, author, location = ticket_query

            ticket_embed = nc.Embed(title=f"Ticket #{ticket_id} :bug:", description=f"Opened by {author} @ {location}.")
            ticket_embed.add_field(name="__Mentor__ :military_helmet:", value=("N/A" if mentor is None else mentor))
            ticket_embed.add_field(
                name="__Claimed__ :face_with_monocle:", value=(":white_check_mark:" if claimed == 1 else ":no_entry:")
            )
            ticket_embed.add_field(
                name="__Closed__ :tada:", value=(":white_check_mark:" if closed == 1 else ":no_entry:")
            )
            ticket_embed.add_field(name="__Message__ :scroll:", value=message, inline=False)

            await ctx.send(embed=ticket_embed, ephemeral=True)

        except Exception as e:
            logging.error(
                f"User {user_name} tried to view a ticket with ID {ticket_id}, but an unexpected error occured: {e}"
            )

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


# view all open tickets {{{1
@bot.slash_command(description="View all open tickets.", guild_ids=[GUILD_ID])
@nc_app_checks.check(
    lambda ctx: ctx.user.get_role(MENTOR_ROLE_ID) is not None or ctx.user.get_role(ORGANIZER_ROLE_ID) is not None  # type: ignore[union-attr]
)
async def opentix(ctx: nc.Interaction) -> None:

    with db_connection:
        try:
            db_cursor = db_connection.cursor()

            # this is an iterable
            tickets_query = db_cursor.execute(
                "SELECT id, author_location, author, message FROM tickets WHERE claimed = 0 AND closed = 0"
            ).fetchall()

            if tickets_query == []:
                await ctx.send("There are no open tickets :sob:", ephemeral=True)

                return

            # get a tuple for each list of fields.
            ticket_ids, locations, authors, messages = zip(*tickets_query)

            # prep the data for embed.
            ticket_ids = map(str, ticket_ids)
            logistics = map(
                (lambda x: f"{x[0]} @ *{x[1][:10] + '...' if len(x[1]) > 10 else x[1]}*"), zip(authors, locations)
            )
            messages = map((lambda x: f"{x[:10]}..." if len(x) > 10 else x), messages)

            tickets_embed = nc.Embed(
                title="Open Tickets :dancer:",
                description="Use `/claim` to claim an open ticket. Use `/status` to see the full details of a ticket.",
            )

            tickets_embed.add_field(name="__ID__ :hash:", value="\n".join(ticket_ids))
            tickets_embed.add_field(name="__Logistics__ :globe_with_meridians:", value="\n".join(logistics))
            tickets_embed.add_field(name="__Message__ :scroll:", value="\n".join(messages))

            await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:
            user_name = (
                ctx.user.nick if isinstance(ctx.user, nc.Member) and ctx.user.nick else (ctx.user.global_name if ctx.user is not None else "Unknown")
            )  # use guild nickname if available, otherwise use global name

            logging.error(f"User {user_name} tried to view all open tickets, but an unexpected error occured: {e}")

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


# view all tickets {{{1
@bot.slash_command(description="View all tickets.", guild_ids=[GUILD_ID])
@nc_app_checks.check(
    lambda ctx: ctx.user.get_role(MENTOR_ROLE_ID) is not None or ctx.user.get_role(ORGANIZER_ROLE_ID) is not None  # type: ignore[union-attr]
)
async def alltix(ctx: nc.Interaction) -> None:

    with db_connection:
        try:
            db_cursor = db_connection.cursor()

            # this is an iterable
            tickets_query = db_cursor.execute("SELECT id, claimed, closed FROM tickets").fetchall()

            if tickets_query == []:
                await ctx.send("There are no tickets :fearful:", ephemeral=True)

                return

            # get a tuple for each list of fields.
            ticket_ids, claimeds, closeds = zip(*tickets_query)

            # prep the data for embed.
            claimeds = map(lambda x: ":white_check_mark:" if x == 1 else ":no_entry:", claimeds)
            closeds = map(lambda x: ":white_check_mark:" if x == 1 else ":no_entry:", closeds)
            ticket_ids = map(str, ticket_ids)

            tickets_embed = nc.Embed(
                title="All Tickets :face_with_spiral_eyes:",
                description="Use `/status` to view information about a specific ticket if you have claimed it. Claim an open ticket with `/claim`.",
            )

            tickets_embed.add_field(name="__ID__ :hash:", value="\n".join(ticket_ids))
            tickets_embed.add_field(name="__Claimed__ :face_with_monocle:", value="\n".join(claimeds))
            tickets_embed.add_field(name="__Closed__ :tada:", value="\n".join(closeds))

            await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:
            user_name = (
                ctx.user.nick if isinstance(ctx.user, nc.Member) and ctx.user.nick else (ctx.user.global_name if ctx.user is not None else "Unknown")
            )  # use guild nickname if available, otherwise use global name

            logging.error(f"User {user_name} tried to view all tickets, but an unexpected error occured: {e}")

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


# leaderboard {{{1
@bot.slash_command(description="View which mentors have closed to most tickets.", guild_ids=[GUILD_ID])
async def leaderboard(ctx: nc.Interaction) -> None:
    with db_connection:
        try:
            db_cursor = db_connection.cursor()

            # this is an iterable
            mentors_query = db_cursor.execute(
                "SELECT name, tickets_claimed, tickets_closed FROM mentors ORDER BY tickets_closed DESC"
            ).fetchall()

            if mentors_query == []:
                await ctx.send("Welp... no mentors have claimed any tickets :skull:", ephemeral=True)

                return

            # get a tuple for each list of fields.
            mentors, num_claimed, num_closed = zip(*mentors_query)

            # prep the data for embed.
            mentors = map(lambda x: f"**#{x[1]}**: {x[0]}", zip(mentors, range(1, len(mentors) + 1)))
            num_claimed = map(str, num_claimed)
            num_closed = map(str, num_closed)

            tickets_embed = nc.Embed(
                title="Mentor Leaderboard :fire:", description="Whoever closes the most tickets wins!"
            )

            tickets_embed.add_field(name="__Mentor__ :military_helmet:", value="\n".join(mentors))
            tickets_embed.add_field(name="__# Claimed__ :face_with_monocle:", value="\n".join(num_claimed))
            tickets_embed.add_field(name="__# Closed__ :tada:", value="\n".join(num_closed))

            await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:
            user_name = (
                ctx.user.nick if isinstance(ctx.user, nc.Member) and ctx.user.nick else (ctx.user.global_name if ctx.user is not None else "Unknown")
            )  # use guild nickname if available, otherwise use global name

            logging.error(
                f"User {user_name} tried to view the mentor leaderboard, but an unexpected error occured: {e}"
            )

            await ctx.send("An unknown error has occured. Please contact a HackKU organizer.", ephemeral=True)


# 1}}}


@bot.event
async def on_raw_reaction_add(payload: nc.RawReactionActionEvent) -> None:  # emoji based verification system
    if payload.message_id == WELCOME_MESSAGE_ID:  # if the added reaction is on our welcome message
        # Note: WELCOME_MESSAGE_ID is something manually set via env var
        if payload.guild_id is None:
            return
        guild = bot.get_guild(payload.guild_id)  # Get the guild the reaction was sent in, should only ever be HackKU
        if guild is None:
            return
        member = await guild.fetch_member(payload.user_id)  # get the member who made the reaction

        # # Just to test to make sure the welcome message is configured correctly
        # print(member)
        # print(f"{member.id} Added a {payload.emoji} reaction")
        # print(str(payload.emoji))

        if payload.emoji == next(
            u for u in guild.emojis if u.name == "mascot_hacker"
        ):  # If reacted with custom guild emoji "mascot_hacker"
            await give_role(member, guild, "Hacker")  # give them the appropriate role

        if payload.emoji == next(u for u in guild.emojis if u.name == "mascot_judge"):
            await give_role(member, guild, "Judge")

        if payload.emoji == next(u for u in guild.emojis if u.name == "mascot_mentor"):
            await give_role(member, guild, "Mentor")

        if payload.emoji == next(u for u in guild.emojis if u.name == "mascot_sponsor"):
            await give_role(member, guild, "Sponsor")

    else:
        pass

async def give_role(member: nc.Member, guild: nc.Guild, role_name: str) -> None:
    # step 1: find the Role class that has the role name
    # Step 2: make sure that member has only that role (No doubles)
    user_roles = []
    for temp_role_name in ["Hacker", "Judge", "Mentor", "Sponsor"]:
        user_roles.append(nc.utils.get(guild.roles, name=temp_role_name))

    for mem_role in member.roles:
        if mem_role in user_roles:  # if the member already has one of our 4 relavent roles
            await member.remove_roles(mem_role)  # remove that non-requested role
            # TODO: make a audit log to show who has switched roles to catch Hackers quickly switching roles for an unfair advantage

    role = nc.utils.get(guild.roles, name=role_name)
    if role is not None:
        await member.add_roles(role)  # gives the user the requested role

# variables for the counting game
current_num = COUNTING_START
last_user_id = None
high_score = COUNTING_START

@bot.event
async def on_message(message: nc.Message) -> None:
    # establishes that global variables are being used
    global current_num, last_user_id, high_score
    # Send announcements to the website announcement endpoint
    if message.channel.id == ANNOUNCEMENT_CHANNEL_ID and message.author != bot.user and len(message.content) > 25:
        try:
            response = requests.post(
                ANNOUNCEMENT_ENDPOINT,
                headers={"X-Announcement-Secret": ANNOUNCEMENT_SECRET},
                json={
                    "content": message.clean_content,
                    "publishedAt": message.created_at.isoformat(),
                    "authorId": str(message.author.id),
                    "authorColor": str(message.author.color),
                    "authorImageUrl": str(message.author.display_avatar),
                    "role": message.author.top_role.name, # type: ignore
                    "authorName": message.author.display_name, # Use the server nickname
                },
            )
            if response.status_code != 200:
                raise Exception(f"Received non-200 response: {response.status_code} - {response.text}")
            announcement = response.json().get("id")
            with db_connection:
                db_connection.execute(
                    "INSERT OR REPLACE INTO announcements (discord_message_id, announcement_id) VALUES (:discord_message_id, :announcement_id)",
                    {"discord_message_id": message.id, "announcement_id": announcement},
                )
            logger.info(
                f"Sent announcement from {message.author.display_name} to announcement endpoint! The announcement ID is {announcement}"
            )
        except Exception as e:
            logger.error(f"Failed to send announcement from {message.author.name}: {e}")

    # Counting channel logic
    elif message.channel.id == COUNTING_CHANNEL_ID and message.author != bot.user:
        # if message content is not strictly a number, or calculates to one (within 5 seconds) ignore
        message_num = convert_to_int(message.content)

        if message_num:
            # message_num = int(message.content)
            print("Calculated value: ", message_num)

            # if number is equal to last numeric message + 1 and is sent by a different author than the last message, keep going and react with a checkmark
            # (also keeps track of high score)
            if message_num and message_num == current_num + 1 and message.author.id != last_user_id:
                current_num += 1
                if current_num > high_score:
                    high_score = current_num
                last_user_id = message.author.id
                await message.add_reaction('✅')
            # otherwise, reset count, reply with message detailing to user what they did wrong, and react with an X
            else:
                old_num = current_num
                current_num = 0
                if message.author.id == last_user_id:
                    await message.reply("**No double-posting!**\nCount reset.")
                elif message_num != old_num + 1:
                    await message.reply(f"Wrong number! The correct number was **{old_num + 1}**.\nHigh score: **{high_score}**\nCount reset.")
                last_user_id = None
                await message.add_reaction('❌')


@bot.event
async def on_message_edit(before: nc.Message, after: nc.Message) -> None:
    # Edit announcement on website if edited in the announcement channel
    if before.channel.id == ANNOUNCEMENT_CHANNEL_ID and before.author != bot.user and before.content != after.content:
        row = db_connection.execute(
            "SELECT announcement_id FROM announcements WHERE discord_message_id = :discord_message_id",
            {"discord_message_id": before.id},
        ).fetchone()
        announcement_id = row[0] if row else None
        if announcement_id:
            try:
                response = requests.patch(
                    ANNOUNCEMENT_ENDPOINT,
                    headers={"X-Announcement-Secret": ANNOUNCEMENT_SECRET},
                    json={"id": announcement_id, "content": after.clean_content},
                )
                if response.status_code != 200:
                    raise Exception(f"Received non-200 response: {response.status_code} - {response.text}")
                logger.info(f"Updated announcement with ID {announcement_id} from message edit by {after.author.name}")
            except Exception as e:
                logger.error(
                    f"Failed to update announcement with ID {announcement_id} from message edit by {after.author.name}: {e}"
                )


@bot.event
async def on_message_delete(message: nc.Message) -> None:
    # Delete announcement on website if deleted in the announcement channel
    if message.channel.id == ANNOUNCEMENT_CHANNEL_ID and message.author != bot.user:
        row = db_connection.execute(
            "SELECT announcement_id FROM announcements WHERE discord_message_id = :discord_message_id",
            {"discord_message_id": message.id},
        ).fetchone()
        announcement_id = row[0] if row else None
        if announcement_id:
            try:
                response = requests.delete(
                    ANNOUNCEMENT_ENDPOINT,
                    headers={"X-Announcement-Secret": ANNOUNCEMENT_SECRET},
                    json={"id": announcement_id},
                )
                if response.status_code != 200:
                    raise Exception(f"Received non-200 response: {response.status_code} - {response.text}")
                with db_connection:
                    db_connection.execute(
                        "DELETE FROM announcements WHERE discord_message_id = :discord_message_id",
                        {"discord_message_id": message.id},
                    )
                logger.info(
                    f"Deleted announcement with ID {announcement_id} from message deletion by {message.author.name}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to delete announcement with ID {announcement_id} from message deletion by {message.author.name}: {e}"
                )


# Run the bot
bot.run(API_TOKEN)
