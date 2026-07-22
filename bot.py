"""Discord bot entry point: !register, !stats, !leaderboard, !help."""
import discord
from discord.ext import commands

import config
import database
from riot_api import SOLO_DUO_QUEUE_ID, RiotAPIError, RiotClient

intents = discord.Intents.default()
intents.message_content = True  # required to read "!stats Name" style command text


class LoLStatsBot(commands.Bot):
    async def setup_hook(self):
        # Runs once inside the bot's event loop, before it connects to
        # Discord's gateway -- the right place to create the aiohttp-backed
        # Riot client, since aiohttp sessions need a running event loop.
        self.riot_client = RiotClient(config.RIOT_API_KEY, region=config.RIOT_REGION)

    async def close(self):
        await self.riot_client.close()
        await super().close()


bot = LoLStatsBot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    # Can fire more than once (e.g. after a reconnect), so one-time setup
    # like database.init_db() happens in main() instead of here.
    # change_presence sets the "Watching ..." text shown under the bot's
    # name in the member list -- visible to everyone, no command needed.
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="!help | !register !stats !leaderboard",
        )
    )
    print(f"Logged in as {bot.user} (id={bot.user.id})")
    print("Commands ready: !register  !stats  !leaderboard  !help")


@bot.command(name="help")
async def help_command(ctx: commands.Context):
    """!help -- show all commands."""
    embed = discord.Embed(
        title="LoL Stats Bot -- Commands",
        description="Tracks Ranked Solo/Duo stats for the group.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="!register Name#Tag",
        value="Start tracking a summoner (Riot ID format, e.g. `!register Faker#KR1`).",
        inline=False,
    )
    embed.add_field(
        name="!stats <name>",
        value="Recent Ranked Solo/Duo KDA, win rate, and top champions for a tracked summoner.",
        inline=False,
    )
    embed.add_field(
        name="!leaderboard",
        value="Ranks all tracked summoners by win rate, based on stored stats.",
        inline=False,
    )
    embed.set_footer(text="Stats accumulate over time -- run !stats for each person periodically.")
    await ctx.send(embed=embed)


@bot.command(name="register")
async def register(ctx: commands.Context, riot_id: str = None):
    """!register Name#Tag -- start tracking a friend's League account."""
    if not riot_id or "#" not in riot_id:
        await ctx.send("Usage: `!register Name#Tag` (e.g. `!register Faker#KR1`)")
        return

    game_name, tag_line = riot_id.split("#", 1)
    async with ctx.typing():
        try:
            puuid = await bot.riot_client.get_puuid_by_riot_id(game_name, tag_line)
        except RiotAPIError as e:
            await ctx.send(f"Riot API error: {e}")
            return

    if puuid is None:
        await ctx.send(f"Couldn't find Riot ID `{riot_id}` -- double-check the name and #tag.")
        return

    stored_id = f"{game_name}#{tag_line}"
    if database.add_summoner(stored_id, game_name, tag_line, puuid, str(ctx.author.id)):
        await ctx.send(f"Now tracking **{stored_id}**.")
    else:
        await ctx.send(f"**{stored_id}** is already tracked.")


@bot.command(name="stats")
async def stats(ctx: commands.Context, *, name: str = None):
    """!stats <name> -- recent ranked KDA, win rate and top champions."""
    if not name:
        await ctx.send("Usage: `!stats <name>` (e.g. `!stats Faker`)")
        return

    summoner = database.find_summoner(name)
    if summoner is None:
        await ctx.send(f"No tracked summoner matches `{name}`. Register them with `!register Name#Tag` first.")
        return

    async with ctx.typing():
        try:
            match_ids = await bot.riot_client.get_solo_duo_match_ids(summoner["puuid"], count=10)
            new_matches = 0
            for match_id in match_ids:
                if database.match_exists(match_id, summoner["puuid"]):
                    continue  # already stored from a previous !stats call

                match = await bot.riot_client.get_match(match_id)
                if match is None:
                    continue

                if match["info"]["queueId"] != SOLO_DUO_QUEUE_ID:
                    continue  # belt-and-suspenders: only ranked solo/duo counts

                participant = next(
                    (p for p in match["info"]["participants"] if p["puuid"] == summoner["puuid"]),
                    None,
                )
                if participant is None:
                    continue

                database.save_match_participation(
                    match_id=match_id,
                    puuid=summoner["puuid"],
                    champion=participant["championName"],
                    kills=participant["kills"],
                    deaths=participant["deaths"],
                    assists=participant["assists"],
                    win=participant["win"],
                    queue_id=match["info"]["queueId"],
                    game_creation=match["info"]["gameCreation"],
                )
                new_matches += 1
        except RiotAPIError as e:
            await ctx.send(f"Riot API error: {e}")
            return

    totals, champs = database.get_summoner_summary(summoner["puuid"])
    games = totals["games"] or 0
    if games == 0:
        await ctx.send(f"No ranked solo/duo matches found yet for **{summoner['riot_id']}**.")
        return

    wins = totals["wins"] or 0
    win_rate = wins / games * 100
    kills, deaths, assists = totals["k"] or 0, totals["d"] or 0, totals["a"] or 0
    kda_ratio = (kills + assists) / deaths if deaths > 0 else float(kills + assists)

    embed = discord.Embed(
        title=f"{summoner['riot_id']} -- Ranked Solo/Duo Stats",
        description=f"Based on {games} stored solo/duo game(s) ({new_matches} fetched just now)",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Win Rate", value=f"{win_rate:.1f}% ({wins}W {games - wins}L)", inline=True)
    embed.add_field(
        name="KDA",
        value=f"{kills / games:.1f} / {deaths / games:.1f} / {assists / games:.1f}  ({kda_ratio:.2f}:1)",
        inline=True,
    )
    if champs:
        champ_lines = [
            f"**{c['champion']}** -- {c['games']}g, {(c['wins'] or 0) / c['games'] * 100:.0f}% WR" for c in champs
        ]
        embed.add_field(name="Top Champions", value="\n".join(champ_lines), inline=False)
    embed.set_footer(
        text="Stats accumulate over time -- each !stats call fetches up to 10 newest ranked solo/duo games."
    )

    await ctx.send(embed=embed)


@bot.command(name="leaderboard")
async def leaderboard(ctx: commands.Context):
    """!leaderboard -- ranks tracked friends by stored win rate."""
    rows = database.get_leaderboard(min_games=1)
    if not rows:
        await ctx.send("No stats stored yet. Run `!stats <name>` for your friends first.")
        return

    lines = []
    for i, row in enumerate(rows, start=1):
        wins, games = row["wins"] or 0, row["games"]
        win_rate = wins / games * 100
        lines.append(f"**{i}. {row['riot_id']}** -- {win_rate:.1f}% WR ({wins}W {games - wins}L)")

    embed = discord.Embed(
        title="Leaderboard -- Win Rate",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="Based on ranked games stored via !stats -- run it for everyone to keep this fresh.")
    await ctx.send(embed=embed)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send(f"Something went wrong: {error}")


def main():
    database.init_db()
    bot.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
