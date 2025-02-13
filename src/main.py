import os
import discord
from discord import app_commands
from pymongo import MongoClient
from dotenv import load_dotenv
import secrets
import datetime
import json
import urllib.parse
import re

load_dotenv()

TOKEN = os.getenv("TOKEN")
BOT_MASTER_ID = int(os.getenv("BOT_MASTER_ID"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client.lawbot
paragraphs_collection = db.paragraphs
fines_collection = db.fines

# Hjelpefunksjon for å finne den laveste ledige heltalls-ID-en for bøter
def get_next_fine_id():
    fines = fines_collection.find({}, {"short_id": 1})
    taken_ids = set()
    for fine in fines:
        if "short_id" in fine:
            try:
                taken_ids.add(int(fine["short_id"]))
            except Exception:
                pass
    # Start på 1 og øk til vi finner et ledig tall
    next_id = 1
    while next_id in taken_ids:
        next_id += 1
    return next_id


# Sett opp Discord-klient med intents
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def is_bot_master(interaction: discord.Interaction) -> bool:
    return interaction.user.id == BOT_MASTER_ID


@client.event
async def on_ready():
    print(f"Logget inn som {client.user} (ID: {client.user.id})")
    test_guild = discord.Object(id=1322336457419001968)
    try:
        print("Synkroniserer kommandoer...")
        # Synkroniserer kun kommandoer for testguild
        # tree.clear_commands(guild=test_guild)
        # tree.copy_global_to(guild=test_guild)
        # synced = await tree.sync(guild=test_guild)
        tree.clear_commands(guild=test_guild)
        synced = await tree.sync(guild=test_guild)
        print(f"Synkroniserte {len(synced)} kommandoer.")
    except Exception as e:
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


# Slash-kommando for å opprette en ny bot (bøte) for en bruker
@tree.command(name="create_fine", description="Danner en ny bot for en bruker")
@app_commands.describe(
    paragraph_identifier="Første bokstaver på kort ID eller tittel på paragrafen som ble brutt",
    description="Beskrivelse av boten",
    num_fines="Antall bøter som skal ilagt",
    offender="Brukeren som skal få boten",
    image="(Valgfritt) Opplastet bilde for dokumentasjon",
)
async def create_fine(
    interaction: discord.Interaction,
    paragraph_identifier: str,
    description: str,
    num_fines: int,
    offender: discord.Member,
    image: discord.Attachment = None,
):
    # Sjekk at brukeren ikke prøver å gi seg selv bot
    if offender.id == interaction.user.id:
        await interaction.response.send_message(
            "🚫 Du kan ikke gi deg selv bot.", ephemeral=True
        )
        return

    # Bruk regex for å søke etter paragraf basert på starten av short_id eller title (case-insensitive)
    regex = re.compile(f"^{re.escape(paragraph_identifier)}", re.IGNORECASE)
    paragraph = paragraphs_collection.find_one(
        {"$or": [{"short_id": regex}, {"title": regex}]}
    )
    if not paragraph:
        await interaction.response.send_message(
            "🚫 Fant ingen paragraf som matcher den gitte identifikatoren.",
            ephemeral=True,
        )
        return

    # Generer en sekvensiell ID for boten: Finn det laveste ledige heltall (starter på 1)
    fine_id = get_next_fine_id()

    image_url = image.url if image else None

    # Lag dokument for boten (bøten)
    fine = {
        "short_id": fine_id,
        "paragraph": {
            "title": paragraph.get("title"),
            "short_id": paragraph.get("short_id"),
        },
        "description": description,
        "num_fines": num_fines,
        "image": image_url,
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
        f"✅ Bot for {offender.mention} er registrert under paragraf **{paragraph.get('title')}** (Paragraf ID: {paragraph.get('short_id')}).\n**Bøte-ID:** {fine_id}",
        ephemeral=False,
    )

    date_str = fine.get("date").strftime("%Y-%m-%d %H:%M:%S")

    detailed_text = (
        f"**Paragraf:** {fine.get('paragraph').get('title')} (ID: {fine.get('paragraph').get('short_id')})\n"
        f"**Beskrivelse:** {fine.get('description')}\n"
        f"**Antall bøter:** {fine.get('num_fines')}\n"
        f"**Godkjent:** {'Ja' if fine.get('approved') else 'Nei'}\n"
        f"**Tilbakebetalt:** {'Ja' if fine.get('reimbursed') else 'Nei'}\n"
        f"**Dato:** {date_str}\n"
        f"**Offender:** {offender.mention}\n"
        f"**Issuer:** {interaction.user.mention}"
    )

    embed = discord.Embed(
        title="Botinformasjon",
        description=detailed_text,
        color=discord.Color.green(),
    )

    if fine.get("image"):
        embed.set_image(url=fine.get("image"))

    await interaction.response.send_message(embed=embed)


# Slash-kommando for å liste en kort oversikt over alle botene (bøtene) for en gitt bruker
@tree.command(
    name="list_fines", description="Vis en kort oversikt over bot for en gitt bruker"
)
@app_commands.describe(user="Brukeren hvis bot du ønsker å se")
async def list_fines(interaction: discord.Interaction, user: discord.Member):
    user_fines = list(fines_collection.find({"offender_id": user.id}))
    if not user_fines:
        await interaction.response.send_message(
            f"📜 Ingen bot funnet for {user.mention}.", ephemeral=True
        )
        return

    # Sorter botene etter dato (nyeste først)
    user_fines.sort(
        key=lambda x: x.get("date", datetime.datetime.now(datetime.timezone.utc)),
        reverse=True,
    )

    # total_fines = len(user_fines)
    total_fines = sum([f.get("num_fines", 0) for f in user_fines])

    # Opprett et overordnet embed med totalantall
    embed = discord.Embed(
        title=f"Bot for {user.display_name}",
        description=f"Totalt antall bot: **{total_fines}**",
        color=discord.Color.blue(),
    )

    for fine in user_fines:
        fine_id = fine.get("short_id", "N/A")
        para_title = fine.get("paragraph", {}).get("title", "Ukjent paragraf")
        date_obj = fine.get("date")
        date_str = (
            date_obj.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(date_obj, datetime.datetime)
            else "N/A"
        )
        num_fines = fine.get("num_fines", 0)
        bilde_status = "Ja" if fine.get("image") else "Nei"

        field_value = (
            f"**Dato:** {date_str}\n"
            f"**Antall bøter:** {num_fines}\n"
            f"**Bilde:** {bilde_status}"
        )
        embed.add_field(
            name=f"ID: {fine_id} | Paragraf: {para_title}",
            value=field_value,
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


# Slash-kommando for å vise detaljert oversikt for en spesifikk bot (bøte)
@tree.command(
    name="list_fine", description="Vis detaljert oversikt for en spesifikk bot"
)
@app_commands.describe(identifier="Den unike ID-en til boten (bøten)")
async def list_fine(interaction: discord.Interaction, identifier: int):
    fine = fines_collection.find_one({"short_id": identifier})
    if not fine:
        await interaction.response.send_message(
            f"⚠️ Ingen bot funnet med ID **{identifier}**.", ephemeral=True
        )
        return

    fine_id = fine.get("short_id", "N/A")
    paragraph_info = fine.get("paragraph", {})
    para_title = paragraph_info.get("title", "Ukjent paragraf")
    para_id = paragraph_info.get("short_id", "N/A")
    fine_desc = fine.get("description", "Ingen beskrivelse")
    num_fines = fine.get("num_fines", 0)
    approved = fine.get("approved", False)
    reimbursed = fine.get("reimbursed", False)
    date_obj = fine.get("date")
    date_str = (
        date_obj.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(date_obj, datetime.datetime)
        else "N/A"
    )
    offender_name = fine.get("offender_name", "Ukjent")
    issuer_name = fine.get("issuer_name", "Ukjent")

    detailed_text = (
        f"**Paragraf:** {para_title} (ID: {para_id})\n"
        f"**Beskrivelse:** {fine_desc}\n"
        f"**Antall bøter:** {num_fines}\n"
        f"**Godkjent:** {'Ja' if approved else 'Nei'}\n"
        f"**Tilbakebetalt:** {'Ja' if reimbursed else 'Nei'}\n"
        f"**Dato:** {date_str}\n"
        f"**Offender:** {offender_name}\n"
        f"**Issuer:** {issuer_name}"
    )

    embed = discord.Embed(
        title=f"Detaljert oversikt for bot ID: {fine_id}",
        description=detailed_text,
        color=discord.Color.green(),
    )

    if fine.get("image"):
        embed.set_image(url=fine.get("image"))

    await interaction.response.send_message(embed=embed)


# Slash-kommando for å fjerne en bot (bøte) (kun for bot-mester/lovverksjef)
@tree.command(
    name="remove_fine", description="Fjern en bot (kun for bot-mester/lovverksjef)"
)
@app_commands.describe(identifier="Den unike ID-en til boten (bøten) som skal fjernes")
async def remove_fine(interaction: discord.Interaction, identifier: int):
    if not is_bot_master(interaction):
        await interaction.response.send_message(
            "🚫 Du har ikke rettigheter til å bruke denne kommandoen.", ephemeral=True
        )
        return

    result = fines_collection.delete_one({"short_id": identifier})
    if result.deleted_count == 0:
        await interaction.response.send_message(
            f"⚠️ Fant ingen bot med ID **{identifier}**.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"✅ Bot med ID **{identifier}** er fjernet.", ephemeral=False
        )


@tree.command(
    name="update_paragraph",
    description="Oppdater en eksisterende paragraf (bot-mester)",
)
@app_commands.describe(
    identifier="Tittelen eller den korte ID-en til paragrafen",
    title="(Valgfritt) Ny tittel",
    description="(Valgfritt) Ny beskrivelse",
    max_fines="(Valgfritt) Ny maks antall bøter",
)
async def update_paragraph(
    interaction: discord.Interaction,
    identifier: str,
    title: str = None,
    description: str = None,
    max_fines: int = None,
):
    if not is_bot_master(interaction):
        await interaction.response.send_message(
            "🚫 Du har ikke rettigheter til å bruke denne kommandoen.", ephemeral=True
        )
        return

    # Finn paragrafen basert på tittel eller short_id
    paragraph = paragraphs_collection.find_one(
        {"$or": [{"title": identifier}, {"short_id": identifier}]}
    )
    if not paragraph:
        await interaction.response.send_message(
            f"⚠️ Ingen paragraf funnet med identifikatoren **{identifier}**.",
            ephemeral=True,
        )
        return

    update_fields = {}
    if title is not None:
        update_fields["title"] = title
    if description is not None:
        update_fields["description"] = description
    if max_fines is not None:
        update_fields["max_fines"] = max_fines

    if not update_fields:
        await interaction.response.send_message(
            "ℹ️ Ingen nye verdier ble sendt inn for oppdatering.", ephemeral=True
        )
        return

    # Oppdater paragrafen
    result = paragraphs_collection.update_one(
        {"_id": paragraph["_id"]}, {"$set": update_fields}
    )
    if result.modified_count == 1:
        await interaction.response.send_message(
            f"✅ Paragraf med identifikatoren **{identifier}** er oppdatert.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "⚠️ Det skjedde en feil under oppdateringen.", ephemeral=True
        )


if __name__ == "__main__":
    client.run(TOKEN)
