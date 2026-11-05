from __future__ import annotations

import discord
from discord import app_commands

from assistant.addons.base import Addon
from assistant.formatting import format_stored, note_problem, note_summary, one_tag, page_slice
from assistant.tools import AssistantTool, ToolContext


class CatalogView(discord.ui.View):
    def __init__(self, cog: Notes, owner_id: int, query: str, tag: str, page: int, total_pages: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.owner_id = owner_id
        self.query = query
        self.tag = tag
        self.page = page
        self.total_pages = total_pages
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.page <= 1
        self.next.disabled = self.page >= self.total_pages

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This catalog is private.", ephemeral=True)
            return False
        return True

    async def _show(self, interaction: discord.Interaction, page: int) -> None:
        embed, self.page, self.total_pages = self.cog.render_catalog(
            self.owner_id, self.query, self.tag, page
        )
        self._sync_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, self.page - 1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, self.page + 1)


class Notes(Addon):
    addon_name = "notes"
    addon_description = "Notes you can save, search, and browse in a catalog."

    note = app_commands.Group(name="note", description="Save, open, edit, and delete notes")

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="save_note",
                description="Save a note in the user's catalog.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title."},
                        "body": {"type": "string", "description": "The note text."},
                        "tags": {
                            "type": "string",
                            "description": "Optional comma-separated tags, such as school, errands.",
                        },
                    },
                    "required": ["title", "body"],
                },
                handler=self._tool_save,
            ),
            AssistantTool(
                name="search_notes",
                description="Search the note catalog by words or tag. Returns titles and ids.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Words to find in the title, text, or tags.",
                        },
                        "tag": {"type": "string", "description": "Optional tag to match."},
                    },
                    "required": [],
                },
                handler=self._tool_search,
            ),
            AssistantTool(
                name="read_note",
                description="Read one note by id, including its full text.",
                parameters={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "integer", "description": "The note id."}
                    },
                    "required": ["note_id"],
                },
                handler=self._tool_read,
            ),
            AssistantTool(
                name="delete_note",
                description=(
                    "Delete a note by id. Use only when the user clearly asks "
                    "to delete that note."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "integer", "description": "The note id."}
                    },
                    "required": ["note_id"],
                },
                handler=self._tool_delete,
            ),
        ]

    def _tool_save(self, ctx: ToolContext, title: str, body: str, tags: str = "") -> str:
        problem = note_problem(title, body)
        if problem:
            return problem
        row = ctx.db.add_note(ctx.user_id, title, body, tags)
        tag_text = f" Tags: {row['tags']}." if row["tags"] else ""
        return f"Saved note #{row['id']}, {row['title']}.{tag_text}"

    def _tool_search(self, ctx: ToolContext, query: str = "", tag: str = "") -> str:
        rows = ctx.db.search_notes(ctx.user_id, query, tag)
        if not rows:
            return "No matching notes."
        lines = [f"#{row['id']} {row['title']} [{row['tags']}]" for row in rows[:8]]
        if len(rows) > 8:
            lines.append(f"{len(rows) - 8} more. Narrow the search.")
        return "\n".join(lines)

    def _tool_read(self, ctx: ToolContext, note_id: int) -> str:
        row = ctx.db.get_note(ctx.user_id, int(note_id))
        if row is None:
            return f"There is no note #{note_id}."
        tags = row["tags"] or "none"
        return f"#{row['id']} {row['title']}\nTags: {tags}\n{row['body']}"

    def _tool_delete(self, ctx: ToolContext, note_id: int) -> str:
        row = ctx.db.delete_note(ctx.user_id, int(note_id))
        if row is None:
            return f"There is no note #{note_id}."
        return f"Deleted note #{row['id']}, {row['title']}."

    def render_catalog(
        self, user_id: int, query: str, tag: str, page: int
    ) -> tuple[discord.Embed, int, int]:
        rows = self.bot.db.search_notes(user_id, query, tag)
        chunk, current, total_pages = page_slice(rows, page)
        embed = discord.Embed(title="Note catalog", color=discord.Color.blurple())
        if not rows:
            embed.description = (
                "No notes yet. Save one with /note add."
                if not query and not tag
                else "No notes match that."
            )
        else:
            embed.description = "\n\n".join(note_summary(note) for note in chunk)[:4000]
        footer = f"Page {current} of {total_pages} · {len(rows)} notes"
        if query:
            footer += f" · search: {query}"
        if tag:
            footer += f" · tag: {tag}"
        embed.set_footer(text=footer[:2048])
        return embed, current, total_pages

    @note.command(name="add", description="Save a note")
    @app_commands.describe(
        title="Short title",
        body="The note",
        tags="Optional comma-separated tags, such as school, errands",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        title: str,
        body: str,
        tags: str = "",
    ) -> None:
        message = self._tool_save(self._ctx(interaction), title, body, tags)
        await interaction.response.send_message(message)

    @note.command(name="show", description="Open one note")
    @app_commands.describe(note_id="The id from /catalog")
    async def show(self, interaction: discord.Interaction, note_id: int) -> None:
        row = self.bot.db.get_note(interaction.user.id, note_id)
        if row is None:
            await interaction.response.send_message(
                f"There is no note #{note_id}."
            )
            return
        embed = discord.Embed(
            title=f"#{row['id']} {row['title']}"[:256],
            description=row["body"][:4000],
            color=discord.Color.blurple(),
        )
        updated = format_stored(row["updated_at"], self.bot.settings.timezone)
        footer = f"Updated {updated}"
        if row["tags"]:
            footer = f"{row['tags']} · {footer}"
        embed.set_footer(text=footer[:2048])
        await interaction.response.send_message(embed=embed)

    @note.command(name="edit", description="Change a note")
    @app_commands.describe(
        note_id="The id from /catalog",
        title="New title. Leave blank to keep it.",
        body="New text. Leave blank to keep it.",
        tags="New tags. Leave this out to keep them. Send - to clear tags.",
    )
    async def edit(
        self,
        interaction: discord.Interaction,
        note_id: int,
        title: str | None = None,
        body: str | None = None,
        tags: str | None = None,
    ) -> None:
        if title is None and body is None and tags is None:
            await interaction.response.send_message(
                "Tell me what to change: title, text, or tags.",
            )
            return
        current = self.bot.db.get_note(interaction.user.id, note_id)
        if current is None:
            await interaction.response.send_message(
                f"There is no note #{note_id}."
            )
            return
        new_title = current["title"] if title is None else title
        new_body = current["body"] if body is None else body
        problem = note_problem(new_title, new_body)
        if problem:
            await interaction.response.send_message(problem)
            return
        stored_tags = None if tags is None else ("" if tags.strip() == "-" else tags)
        row = self.bot.db.update_note(
            interaction.user.id,
            note_id,
            title=None if title is None else new_title,
            body=None if body is None else new_body,
            tags=stored_tags,
        )
        if row is None:
            await interaction.response.send_message(
                f"There is no note #{note_id}."
            )
            return
        await interaction.response.send_message(
            f"Updated note #{row['id']}, {row['title']}.",
        )

    @note.command(name="delete", description="Delete a note")
    @app_commands.describe(note_id="The id from /catalog")
    async def delete(self, interaction: discord.Interaction, note_id: int) -> None:
        message = self._tool_delete(self._ctx(interaction), note_id)
        await interaction.response.send_message(message)

    @app_commands.command(name="catalog", description="Browse and search your notes")
    @app_commands.describe(
        query="Words to look for in titles and notes",
        tag="Only notes with this tag",
        page="Page number, starting at 1",
    )
    async def catalog(
        self,
        interaction: discord.Interaction,
        query: str | None = None,
        tag: str | None = None,
        page: int = 1,
    ) -> None:
        cleaned_query = (query or "").strip()
        cleaned_tag = one_tag(tag or "")
        embed, current, total_pages = self.render_catalog(
            interaction.user.id, cleaned_query, cleaned_tag, page
        )
        view = None
        if total_pages > 1:
            view = CatalogView(
                self,
                interaction.user.id,
                cleaned_query,
                cleaned_tag,
                current,
                total_pages,
            )
        await interaction.response.send_message(embed=embed, view=view)

    def _ctx(self, interaction: discord.Interaction) -> ToolContext:
        return ToolContext(interaction.user.id, self.bot.settings, self.bot.db)


async def setup(bot) -> None:
    await bot.add_cog(Notes(bot))
