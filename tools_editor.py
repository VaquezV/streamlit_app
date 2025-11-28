"""
Streamlit app to browse and edit the MethodIA/tools collection.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection


st.set_page_config(page_title="MethodIA tools", layout="wide")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _human_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the human portion of the document when present."""
    if isinstance(doc.get("human"), dict):
        return doc["human"]
    return doc


def _editable_view(doc: dict[str, Any]) -> dict[str, Any]:
    source = _human_doc(doc)
    excluded_keys = {
        "_id",
        "update_history",
        "last_updated_at",
        "last_updated_by",
        "verified_by",
        "verified_at",
    }
    return {k: v for k, v in source.items() if k not in excluded_keys}


def _diff(original: dict[str, Any], updated: dict[str, Any]) -> dict[str, list[str]]:
    added = []
    removed = []
    changed = []
    for key in updated:
        if key not in original:
            added.append(key)
        elif original[key] != updated[key]:
            changed.append(key)
    for key in original:
        if key not in updated:
            removed.append(key)
    return {"added": sorted(added), "removed": sorted(removed), "changed": sorted(changed)}


def _load_allowed_users() -> dict[str, str]:
    for key in ("users", "app_users", "auth_users"):
        try:
            raw = st.secrets[key]
        except Exception:
            continue
        try:
            return {str(k): str(v) for k, v in dict(raw).items()}
        except Exception:
            continue
    return {}


@st.cache_resource
def _get_collection() -> Collection:
    mongo_uri = st.secrets["mongo"]["uri"]
    client = MongoClient(mongo_uri)
    return client["MethodIA"]["tools"]


def _load_tool_list(
    collection: Collection, search: str, limit: int
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    query: dict[str, Any] = {}
    if search:
        regex = {"$regex": search, "$options": "i"}
        query = {
            "$or": [
                {"ID_tool": regex},
                {"human.ID_tool": regex},
                {"human.Nom_original": regex},
                {"human.Nom_francais": regex},
            ]
        }
    cursor = (
        collection.find(
            query,
            {"ID_tool": 1, "human.ID_tool": 1, "human.Nom_original": 1, "human.Nom_francais": 1},
        )
        .sort("ID_tool", 1)
        .limit(limit)
    )
    ids: list[str] = []
    summaries: dict[str, dict[str, Any]] = {}
    for doc in cursor:
        tool_id = doc.get("ID_tool") or doc.get("human", {}).get("ID_tool")
        if not tool_id:
            continue
        ids.append(tool_id)
        human_part = doc.get("human", {})
        summaries[tool_id] = {
            "Nom_original": human_part.get("Nom_original", doc.get("Nom_original", "")),
            "Nom_francais": human_part.get("Nom_francais", doc.get("Nom_francais", "")),
        }
    return ids, summaries


def _load_tool(collection: Collection, tool_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    full_doc = collection.find_one({"$or": [{"ID_tool": tool_id}, {"human.ID_tool": tool_id}]})
    if not full_doc:
        return None, None
    return full_doc, _editable_view(full_doc)


def _require_login() -> str:
    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user:
        st.sidebar.success(f"Connecte en tant que {st.session_state.user}")
        if st.sidebar.button("Se deconnecter"):
            st.session_state.user = None
            st.rerun()
        return st.session_state.user

    allowed = _load_allowed_users()
    st.sidebar.header("Connexion")
    if not allowed:
        st.sidebar.error("Aucun utilisateur configure dans st.secrets.")
        st.stop()

    username = st.sidebar.text_input("Utilisateur")
    password = st.sidebar.text_input("Mot de passe", type="password")
    if st.sidebar.button("Se connecter"):
        if username in allowed and password == allowed[username]:
            st.session_state.user = username
            st.rerun()
        else:
            st.sidebar.error("Identifiants invalides")
    st.stop()


def _refresh_tool_list(collection: Collection, search: str, limit: int) -> None:
    ids, summaries = _load_tool_list(collection, search, limit)
    st.session_state.tool_ids = ids
    st.session_state.tool_summaries = summaries
    st.session_state.current_index = 0
    st.session_state.search_text = search
    st.session_state.list_limit = limit


def _clear_field_state(tool_id: str) -> None:
    prefix = f"field_widget_{tool_id}_"
    to_delete = [k for k in st.session_state.keys() if k.startswith(prefix)]
    for k in to_delete:
        del st.session_state[k]


def _reset_if_not_str(key: str) -> None:
    """Delete widget state when not a string to avoid Streamlit type errors."""
    if key in st.session_state and not isinstance(st.session_state[key], str):
        del st.session_state[key]


def _render_metadata_article(meta: dict[str, Any], tool_id: str) -> tuple[dict[str, Any], list[str]]:
    """Dedicated editor for Metadata_article fields."""
    meta = meta or {}
    errors: list[str] = []
    prefix = f"field_widget_{tool_id}_metadata_"

    def _maybe_int(val: str | None) -> int | str | None:
        if val is None:
            return None
        val = val.strip()
        if val.isdigit():
            try:
                return int(val)
            except Exception:
                return val
        return val or None

    title = st.text_input("Titre de l'article", meta.get("title", ""), key=prefix + "title")
    abstract = st.text_area("Résumé", meta.get("abstract", ""), key=prefix + "abstract", height=120)
    reference = st.text_area(
        "Référence bibliographique",
        meta.get("Reference_bibliographique", ""),
        key=prefix + "reference",
        height=80,
    )
    discipline = st.text_input("Discipline", meta.get("Discipline", ""), key=prefix + "discipline")
    definition_gp = st.text_area(
        "Définition grand public",
        meta.get("Definition_grand_public", ""),
        key=prefix + "definition",
        height=80,
    )
    annee_pub = st.text_input(
        "Année de publication",
        str(meta.get("Annee_publication", "") or ""),
        key=prefix + "annee_publication",
    )
    keywords_text = st.text_area(
        "Mots-clés (1 par ligne)",
        "\n".join(meta.get("keywords", [])),
        key=prefix + "keywords",
        height=80,
    )
    champs_etude_text = st.text_area(
        "Champs d'étude (1 par ligne)",
        "\n".join(meta.get("Champ_etude", [])),
        key=prefix + "champ_etude",
        height=80,
    )
    authors_text = st.text_area(
        "Auteurs (format: Nom | Affiliation, un par ligne)",
        "\n".join(
            [
                f"{a.get('name','')} | {a.get('affiliation','')}"
                for a in meta.get("authors", [])
                if isinstance(a, dict)
            ]
        ),
        key=prefix + "authors",
        height=120,
    )
    journal = meta.get("journal", {}) or {}
    jr_name = st.text_input("Revue", journal.get("Nom_Revue", ""), key=prefix + "journal_nom")
    jr_year = st.text_input("Année revue", str(journal.get("year", "") or ""), key=prefix + "journal_year")
    jr_volume = st.text_input("Volume", journal.get("volume", ""), key=prefix + "journal_volume")
    jr_issue = st.text_input("Numéro", journal.get("issue", ""), key=prefix + "journal_issue")
    jr_pages = st.text_input("Pages", journal.get("pages", ""), key=prefix + "journal_pages")

    parsed_authors: list[dict[str, str]] = []
    for line in authors_text.splitlines():
        if not line.strip():
            continue
        if "|" in line:
            name_part, aff_part = line.split("|", 1)
            parsed_authors.append({"name": name_part.strip(), "affiliation": aff_part.strip()})
        else:
            parsed_authors.append({"name": line.strip(), "affiliation": ""})

    updated = {
        "title": title,
        "abstract": abstract,
        "Reference_bibliographique": reference,
        "Discipline": discipline,
        "Definition_grand_public": definition_gp,
        "Annee_publication": _maybe_int(annee_pub),
        "keywords": [k.strip() for k in keywords_text.splitlines() if k.strip()],
        "Champ_etude": [k.strip() for k in champs_etude_text.splitlines() if k.strip()],
        "authors": parsed_authors,
        "journal": {
            "Nom_Revue": jr_name,
            "year": _maybe_int(jr_year),
            "volume": jr_volume or "",
            "issue": jr_issue or "",
            "pages": jr_pages or "",
        },
    }
    # preserve untouched fields
    for k, v in meta.items():
        if k not in updated:
            updated[k] = v
    return updated, errors


def _render_items(items: list[Any], tool_id: str) -> tuple[list[Any], list[str]]:
    """Render each item separately for easier editing."""
    updated_items: list[Any] = []
    errors: list[str] = []
    extra_key = f"field_widget_{tool_id}_items_extra_count"
    extra_count = st.session_state.get(extra_key, 0)
    if st.button("Ajouter un item", key=extra_key + "_add"):
        st.session_state[extra_key] = extra_count + 1
        st.rerun()

    working_items = list(items) + [{} for _ in range(extra_count)]
    for idx, item in enumerate(working_items):
        if not isinstance(item, dict):
            updated_items.append(item)
            continue
        label = f"Item {idx + 1}"
        with st.expander(label, expanded=False):
            prefix = f"field_widget_{tool_id}_item_{idx}_"
            id_val = st.number_input(
                "Identifiant (id)",
                value=float(item.get("id", idx + 1)),
                key=prefix + "id",
                step=1.0,
            )
            question = st.text_area("Question", item.get("question", ""), key=prefix + "question", height=80)
            facteur = st.text_input("Facteur", item.get("facteur", ""), key=prefix + "facteur")
            options_text = st.text_area(
                "Options (1 par ligne)",
                "\n".join(item.get("options", [])),
                key=prefix + "options",
                height=80,
            )
            note = st.text_input("Note", item.get("note", ""), key=prefix + "note")
            section = st.text_input("Section", item.get("section", ""), key=prefix + "section")

            updated_items.append(
                {
                    "id": int(id_val) if float(id_val).is_integer() else id_val,
                    "question": question,
                    "facteur": facteur or None,
                    "options": [o.strip() for o in options_text.splitlines() if o.strip()],
                    "note": note or None,
                    "section": section or None,
                }
            )
    return updated_items, errors


def _save_tool(
    collection: Collection,
    full_doc: dict[str, Any],
    original_editable: dict[str, Any],
    edited_doc: dict[str, Any],
    user: str,
) -> tuple[bool, str]:
    parsed = deepcopy(edited_doc)
    human_part = _human_doc(full_doc)
    tool_id = human_part.get("ID_tool") or full_doc.get("ID_tool")
    if not tool_id:
        return False, "Impossible de retrouver l'ID_tool."

    if parsed.get("ID_tool", tool_id) != tool_id:
        return False, "ID_tool ne peut pas etre modifie."
    parsed["ID_tool"] = tool_id

    now = datetime.now(timezone.utc).isoformat()
    diff = _diff(original_editable, parsed)
    history_entry = {
        "timestamp": now,
        "user": user,
        "added": diff["added"],
        "removed": diff["removed"],
        "changed": diff["changed"],
    }

    replacement = deepcopy(full_doc)
    target = replacement["human"] if isinstance(replacement.get("human"), dict) else replacement
    target.update(parsed)
    target["last_updated_at"] = now
    target["last_updated_by"] = user
    target["verified_by"] = user
    target["verified_at"] = now
    target["update_history"] = (human_part.get("update_history") or []) + [history_entry]
    replacement["ID_tool"] = tool_id

    try:
        result = collection.replace_one({"_id": full_doc["_id"]}, replacement)
    except Exception as exc:  # pragma: no cover - defensive path
        return False, f"Erreur pendant l'enregistrement: {exc}"

    if result.matched_count == 0:
        return False, "Document introuvable ou non mis a jour."
    return True, f"Outil {tool_id} mis a jour."


def _render_field_input(
    name: str, value: Any, tool_id: str
) -> tuple[Any, str | None]:
    """Render an input for a single field and return (new_value, error)."""
    key = f"field_widget_{tool_id}_{name}"
    label = str(name).replace("_", " ")
    error: str | None = None

    # ID is read-only
    if name == "ID_tool":
        st.text_input(label, value=str(value), disabled=True, key=key)
        return value, None

    # None becomes empty string to edit
    if value is None:
        value = ""

    if isinstance(value, bool):
        new_val = st.checkbox(label, value=value, key=key)
        return new_val, None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        new_val = st.number_input(label, value=float(value), key=key)
        # cast back to int when possible
        if isinstance(value, int) and float(new_val).is_integer():
            return int(new_val), None
        return new_val, None

    if isinstance(value, str):
        if len(value) > 120:
            _reset_if_not_str(key)
            new_val = st.text_area(label, value=value, key=key, height=120)
        else:
            _reset_if_not_str(key)
            new_val = st.text_input(label, value=value, key=key)
        return new_val, None

    if name == "Items" and isinstance(value, list):
        return _render_items(value, tool_id)

    if isinstance(value, list):
        if all(isinstance(x, str) for x in value):
            _reset_if_not_str(key)
            new_val_text = st.text_area(
                label,
                value="\n".join(value),
                key=key,
                help="Une valeur par ligne",
                height=120,
            )
            new_list = [line.strip() for line in new_val_text.splitlines() if line.strip()]
            return new_list, None
        _reset_if_not_str(key)
        json_text = st.text_area(
            label,
            value=json.dumps(value, ensure_ascii=False, indent=2, default=_json_default),
            key=key,
            help="Liste complexe (JSON)",
            height=160,
        )
        try:
            parsed = json.loads(json_text) if json_text.strip() else []
        except json.JSONDecodeError as exc:
            error = f"{name}: JSON invalide ({exc})"
            parsed = value
        return parsed, error

    if name == "Metadata_article" and isinstance(value, dict):
        return _render_metadata_article(value, tool_id)

    if isinstance(value, dict):
        _reset_if_not_str(key)
        json_text = st.text_area(
            label,
            value=json.dumps(value, ensure_ascii=False, indent=2, default=_json_default),
            key=key,
            help="Objet JSON",
            height=200,
        )
        try:
            parsed_dict = json.loads(json_text) if json_text.strip() else {}
        except json.JSONDecodeError as exc:
            error = f"{name}: JSON invalide ({exc})"
            parsed_dict = value
        return parsed_dict, error

    # Fallback: display as string
    _reset_if_not_str(key)
    new_val = st.text_input(label, value=str(value), key=key)
    return new_val, None


def main() -> None:
    st.title("MethodIA tools")
    st.caption("Consulter et modifier les documents de la collection MethodIA/tools (ID non modifiable).")

    user = _require_login()

    try:
        collection = _get_collection()
    except Exception as exc:
        st.error(f"Connexion Mongo impossible: {exc}")
        st.stop()

    # Session defaults
    st.session_state.setdefault("tool_ids", [])
    st.session_state.setdefault("tool_summaries", {})
    st.session_state.setdefault("current_index", 0)
    st.session_state.setdefault("search_text", "")
    st.session_state.setdefault("list_limit", 50)

    # flash message after rerun
    if "flash_success" in st.session_state:
        st.success(st.session_state.pop("flash_success"))

    with st.sidebar:
        st.header("Navigation")
        search = st.text_input("Filtrer (ID ou nom)", value=st.session_state.search_text)
        limit = st.number_input("Taille de la liste", min_value=1, max_value=500, value=int(st.session_state.list_limit))
        if st.button("Recharger la liste") or not st.session_state.tool_ids:
            _refresh_tool_list(collection, search, int(limit))

        st.caption(f"{len(st.session_state.tool_ids)} outil(s) charges.")

        selected_id: str | None = None
        if st.session_state.tool_ids:
            # keep selection when rerunning after save
            if "reload_tool" in st.session_state and st.session_state.reload_tool in st.session_state.tool_ids:
                st.session_state.current_index = st.session_state.tool_ids.index(st.session_state.reload_tool)

            prev_col, next_col = st.columns(2)
            if prev_col.button("Prec"):
                st.session_state.current_index = max(0, st.session_state.current_index - 1)
                st.session_state.tool_selector = st.session_state.tool_ids[st.session_state.current_index]
            if next_col.button("Suiv"):
                st.session_state.current_index = min(
                    len(st.session_state.tool_ids) - 1, st.session_state.current_index + 1
                )
                st.session_state.tool_selector = st.session_state.tool_ids[st.session_state.current_index]

            summaries = st.session_state.tool_summaries
            selected_id = st.selectbox(
                "Outil",
                options=st.session_state.tool_ids,
                index=st.session_state.current_index,
                format_func=lambda tool_id: f"{tool_id} - {summaries.get(tool_id, {}).get('Nom_original', '')}",
                key="tool_selector",
            )
            st.session_state.current_index = st.session_state.tool_ids.index(selected_id)

    if not selected_id:
        st.info("Chargez la liste puis choisissez un outil.")
        return

    full_doc, editable_doc = _load_tool(collection, selected_id)
    if not full_doc or editable_doc is None:
        st.error("Impossible de charger ce document.")
        return
    human_doc = _human_doc(full_doc)

    needs_reload = st.session_state.get("reload_tool") == selected_id
    if st.session_state.get("current_tool_loaded") != selected_id or needs_reload:
        _clear_field_state(selected_id)
        st.session_state.current_tool_loaded = selected_id
        st.session_state.original_editable = deepcopy(editable_doc)
        if needs_reload:
            st.session_state.pop("reload_tool", None)

    # Zone principale plein écran
    st.subheader(f"{selected_id}")
    st.caption(
        f"Derniere mise a jour : {human_doc.get('last_updated_at', 'n/a')} par {human_doc.get('last_updated_by', 'n/a')}"
    )
    history = human_doc.get("update_history") or []
    with st.expander("Historique des sauvegardes", expanded=False):
        if not history:
            st.write("Aucune sauvegarde enregistree.")
        else:
            for entry in reversed(history[-20:]):  # show last 20
                st.write(f"{entry.get('timestamp', '?')} - {entry.get('user', '?')}")
                added = entry.get("added") or []
                removed = entry.get("removed") or []
                changed = entry.get("changed") or []
                if added or removed or changed:
                    st.caption(
                        f"ajoutes: {', '.join(added) or '-'} | supprimes: {', '.join(removed) or '-'} | modifies: {', '.join(changed) or '-'}"
                    )

    tab_fields, tab_raw = st.tabs(["Champs", "JSON brut"])

    with tab_fields:
        preferred_order = [
            "ID_tool",
            "Nom_original",
            "Nom_francais",
            "DOI",
            "PDF",
            "Metadata_article",
            "Outil",
            "Items",
            "References",
            "Echantillons_validation",
            "Licence",
            "Cout",
            "Traductions_validees",
            "Resultats_cles",
            "Signification",
            "Articles_lies",
            "notes",
        ]
        ordered_keys: list[str] = []
        for key in preferred_order:
            if key in editable_doc:
                ordered_keys.append(key)
        for key in sorted(editable_doc.keys()):
            if key not in ordered_keys:
                ordered_keys.append(key)

        with st.form("edit_form"):
            updated_doc: dict[str, Any] = {}
            errors: list[str] = []
            for field in ordered_keys:
                new_val, err = _render_field_input(field, editable_doc[field], selected_id)
                updated_doc[field] = new_val
                if err:
                    errors.append(err)

            submitted = st.form_submit_button("Enregistrer les modifications", type="primary")
            if submitted:
                if errors:
                    st.error("Corrigez les champs invalides : " + "; ".join(errors))
                else:
                    ok, message = _save_tool(
                        collection,
                        full_doc,
                        st.session_state.original_editable,
                        updated_doc,
                        user,
                    )
                    if ok:
                        st.session_state.flash_success = message
                        st.session_state.reload_tool = selected_id
                        st.rerun()
                    else:
                        st.error(message)

    with tab_raw:
        st.caption("Visualisation brute (lecture seule)")
        st.code(json.dumps(editable_doc, indent=2, ensure_ascii=False, default=_json_default))


if __name__ == "__main__":  # pragma: no cover
    main()
