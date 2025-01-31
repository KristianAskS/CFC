import os
import discord
from discord import app_commands
from pymongo import MongoClient
from dotenv import load_dotenv
import secrets  # Brukes for å generere en kort, unik ID
import datetime  # For å hente nåværende dato og tid

# Last inn miljøvariabler fra .env-filen
load_dotenv()

TOKEN = os.getenv("TOKEN")
BOT_MASTER_ID = int(os.getenv("BOT_MASTER_ID"))
MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://mongo:27017"
)  # Standard til docker-compose-tjenestenavn

# Koble til MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client.lawbot
paragraphs_collection = db.paragraphs
fines_collection = db.fines

# Sett opp Discord-klient med intents
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Funksjon for å sjekke om brukeren er bot-mester (eller lovverksjef)
def is_bot_master(interaction: discord.Interaction) -> bool:
    return interaction.user.id == BOT_MASTER_ID


@client.event
async def on_ready():
    print(f"Logget inn som {client.user} (ID: {client.user.id})")
    test_guild = discord.Object(id=1322336457419001968)  # Bytt ut med din testguild-ID
    try:
        # Synkroniserer kun kommandoer for testguild (oppdateres umiddelbart)
        # tree.clear_commands(guild=test_guild)
        # tree.copy_global_to(guild=test_guild)
        synced = await tree.sync(guild=test_guild)
        # print(f"Synkroniserte {len(synced)} kommandoer.")
    except Exception as e:
        # print(f"Feil ved synkronisering av kommandoer: {e}")
        pass


# Slash-kommando for å legge til en paragraf (kun for bot-mester)
@tree.command(
    name="add_paragraph", description="Legg til en ny lovparagraf (bot-mester)"
)
@app_commands.describe(
    title="Paragrafens tittel", description="Beskrivelse", max_fines="Maks antall bøter"
)
async def add_paragraph(
    interaction: discord.Interaction, title: str, description: str, max_fines: int
):
    if not is_bot_master(interaction):
        await interaction.response.send_message(
            "🚫 Du har ikke rettigheter til å bruke denne kommandoen.", ephemeral=True
        )
        return

    # Generer en kort, unik ID for paragrafen (6 hex-tegn)
    short_id = secrets.token_hex(3)
    while paragraphs_collection.find_one({"short_id": short_id}):
        short_id = secrets.token_hex(3)

    # Lag dokument for paragrafen med den nye short_id
    paragraph = {
        "title": title,
        "description": description,
        "max_fines": max_fines,
        "short_id": short_id,
    }
    paragraphs_collection.insert_one(paragraph)
    await interaction.response.send_message(
        f"✅ Paragraf **{title}** (ID: {short_id}) er lagt til.", ephemeral=True
    )


# Slash-kommando for å fjerne en paragraf (kun for bot-mester)
@tree.command(name="remove_paragraph", description="Fjern en lovparagraf (bot-mester)")
@app_commands.describe(
    identifier="Tittelen eller den korte ID-en på paragrafen som skal fjernes"
)
async def remove_paragraph(interaction: discord.Interaction, identifier: str):
    if not is_bot_master(interaction):
        await interaction.response.send_message(
            "🚫 Du har ikke rettigheter til å bruke denne kommandoen.", ephemeral=True
        )
        return

    # Slett paragrafen enten basert på tittel eller short_id
    result = paragraphs_collection.delete_one(
        {"$or": [{"title": identifier}, {"short_id": identifier}]}
    )
    if result.deleted_count == 0:
        await interaction.response.send_message(
            f"⚠️ Fant ingen paragraf med identifikatoren **{identifier}**.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"✅ Paragraf med identifikatoren **{identifier}** er fjernet.",
            ephemeral=True,
        )


# Slash-kommando for å liste alle paragrafer (tilgjengelig for alle)
@tree.command(name="list_paragraphs", description="Vis alle lovparagrafer")
async def list_paragraphs(interaction: discord.Interaction):
    paragraphs = list(paragraphs_collection.find())
    if not paragraphs:
        await interaction.response.send_message("📜 Ingen paragrafer funnet.")
        return

    embed = discord.Embed(
        title="📜 Lovverk",
        description="Liste over alle paragrafer",
        color=discord.Color.blue(),
    )
    for p in paragraphs:
        title = p.get("title", "Uten tittel")
        description = p.get("description", "")
        max_fines = p.get("max_fines", "Ukjent")
        short_id = p.get("short_id", "N/A")
        embed.add_field(
            name=f"⚖️ {title} (ID: {short_id})",
            value=f"{description}\n**Maks antall bøter:** {max_fines}",
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


# Slash-kommando for å danne en ny bot (fine)
# Alle kan bruke denne kommandoen, men man kan ikke gi seg selv bot.
@tree.command(name="create_fine", description="Danner en ny bot for en bruker")
@app_commands.describe(
    paragraph_identifier="Kort ID eller tittel på paragrafen som ble brutt",
    description="Beskrivelse av boten",
    num_fines="Antall bøter som skal ilagt",
    offender="Brukeren som skal få boten",
    image="(Valgfritt) URL til et bilde som dokumentasjon",
)
async def create_fine(
    interaction: discord.Interaction,
    paragraph_identifier: str,
    description: str,
    num_fines: int,
    offender: discord.Member,
    image: str = None,
):
    # Sjekk at brukeren ikke prøver å gi seg selv bot
    if offender.id == interaction.user.id:
        await interaction.response.send_message(
            "🚫 Du kan ikke gi deg selv bot.", ephemeral=True
        )
        return

    # Finn paragrafen basert på short_id eller tittel
    paragraph = paragraphs_collection.find_one(
        {"$or": [{"short_id": paragraph_identifier}, {"title": paragraph_identifier}]}
    )
    if not paragraph:
        await interaction.response.send_message(
            "🚫 Fant ingen paragraf med den gitte identifikatoren.", ephemeral=True
        )
        return

    # Generer en kort, unik ID for boten (6 hex-tegn)
    fine_short_id = secrets.token_hex(3)
    while fines_collection.find_one({"short_id": fine_short_id}):
        fine_short_id = secrets.token_hex(3)

    # Lag dokument for boten
    fine = {
        "short_id": fine_short_id,
        "paragraph": {
            "title": paragraph.get("title"),
            "short_id": paragraph.get("short_id"),
        },
        "description": description,
        "num_fines": num_fines,
        "image": image if image else None,
        "approved": False,
        "reimbursed": False,
        "offender_id": offender.id,
        "offender_name": str(offender),
        "issuer_id": interaction.user.id,
        "issuer_name": str(interaction.user),
        "date": datetime.datetime.utcnow(),
    }
    fines_collection.insert_one(fine)
    await interaction.response.send_message(
        f"✅ Bot for {offender.mention} er registrert under paragraf **{paragraph.get('title')}** (Paragraf ID: {paragraph.get('short_id')}).\n**Fine ID:** {fine_short_id}",
        ephemeral=True,
    )


# Slash-kommando for å liste alle botene for en gitt bruker
@tree.command(name="list_fines", description="Vis alle bot for en gitt bruker")
@app_commands.describe(user="Brukeren hvis bot du ønsker å se")
async def list_fines(interaction: discord.Interaction, user: discord.Member):
    user_fines = list(fines_collection.find({"offender_id": user.id}))
    if not user_fines:
        await interaction.response.send_message(
            f"📜 Ingen bøter funnet for {user.mention}.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"Bot for {user}",
        description="Liste over alle registrerte bot",
        color=discord.Color.red(),
    )
    # Sorter botene etter dato (nyeste først)
    user_fines.sort(
        key=lambda x: x.get("date", datetime.datetime.utcnow()), reverse=True
    )
    for fine in user_fines:
        paragraph_info = fine.get("paragraph", {})
        para_title = paragraph_info.get("title", "Ukjent paragraf")
        para_id = paragraph_info.get("short_id", "N/A")
        fine_desc = fine.get("description", "")
        num_fines = fine.get("num_fines", 0)
        approved = fine.get("approved", False)
        reimbursed = fine.get("reimbursed", False)
        date_obj = fine.get("date")
        date_str = (
            date_obj.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(date_obj, datetime.datetime)
            else "N/A"
        )
        fine_short_id = fine.get("short_id", "N/A")

        field_value = (
            f"**Beskrivelse:** {fine_desc}\n"
            f"**Antall bøter:** {num_fines}\n"
            f"**Godkjent:** {'Ja' if approved else 'Nei'}\n"
            f"**Tilbakebetalt:** {'Ja' if reimbursed else 'Nei'}\n"
            f"**Dato:** {date_str}\n"
            f"**Fine ID:** {fine_short_id}"
        )
        # Legg også ved bilde-URL om den finnes
        if fine.get("image"):
            field_value += f"\n**Bilde:** {fine.get('image')}"

        embed.add_field(
            name=f"⚖️ {para_title} (Paragraf ID: {para_id})",
            value=field_value,
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


# Slash-kommando for å fjerne en bot (kun for bot-mester/lovverksjef)
@tree.command(
    name="remove_fine", description="Fjern en bot (kun for bot-mester/lovverksjef)"
)
@app_commands.describe(identifier="Den unike short ID-en til boten som skal fjernes")
async def remove_fine(interaction: discord.Interaction, identifier: str):
    if not is_bot_master(interaction):
        await interaction.response.send_message(
            "🚫 Du har ikke rettigheter til å bruke denne kommandoen.", ephemeral=True
        )
        return

    result = fines_collection.delete_one({"short_id": identifier})
    if result.deleted_count == 0:
        await interaction.response.send_message(
            f"⚠️ Fant ingen bot med identifikatoren **{identifier}**.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"✅ Bot med identifikatoren **{identifier}** er fjernet.", ephemeral=True
        )


if __name__ == "__main__":
    client.run(TOKEN)
