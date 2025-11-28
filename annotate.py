# streamlit_app/annotate.py
# Mini-app Streamlit pour annoter les articles (présence questionnaire)
# Auteur : Vincent Vaquez
# Date : 2025-10-03

import streamlit as st
from pymongo import MongoClient
import datetime
from datetime import datetime, timezone
# --- Connexion Mongo Atlas ---
MONGO_URI = st.secrets["mongo"]["uri"]  # ⚠️ stocker ton URI dans .streamlit/secrets.toml
client = MongoClient(MONGO_URI)
db = client["scitools"]
col_articles = db["hal_articles"]

# --- Login simple ---
if "user" not in st.session_state:
    st.session_state.user = None

# if st.session_state.user is None:
#     st.title("Connexion annotateur")
#     username = st.text_input("Nom utilisateur")
#     password = st.text_input("Mot de passe", type="password")

#     if st.button("Se connecter"):
#         # ⚠️ démo : mots de passe en dur
#         allowed_users = {"mathilde": "secret123", "vincent": "azerty"}
#         if username in allowed_users and password == allowed_users[username]:
#             st.session_state.user = username
#             st.rerun()
#         else:
#             st.error("Identifiants invalides")
#     st.stop()

annotator = "test"
st.sidebar.success(f"Connecté en tant que **{annotator}**")
st.set_page_config(layout="wide")
# --- Compteurs d'annotation ---
total_articles = col_articles.count_documents({})
annotated_total = col_articles.count_documents({"annotations": {"$exists": True, "$ne": []}})
annotated_by_user = col_articles.count_documents({"annotations.annotator": annotator})

contains_questionnaire = col_articles.count_documents({"annotations.decision": True})
no_questionnaire = col_articles.count_documents({"annotations.decision": False})

contains_by_user = col_articles.count_documents({
    "annotations": {"$elemMatch": {"annotator": annotator, "decision": True}}
})
no_by_user = col_articles.count_documents({
    "annotations": {"$elemMatch": {"annotator": annotator, "decision": False}}
})

# --- Répartition par score_questionnaire ---
score_buckets = col_articles.aggregate([
    {
        "$group": {
              "_id": {"$ifNull": ["$score_questionnaire", "—"]}, 
            "total": {"$sum": 1},
            "annotated": {
                "$sum": {
                    "$cond": [
                        {"$gt": [{"$size": {"$ifNull": ["$annotations", []]}}, 0]},
                        1,
                        0
                    ]
                }
            }
        }
    },
    {"$sort": {"_id": -1}}
])

score_lines = []
for b in score_buckets:
    score = b["_id"] or 0
    line = f"⭐ {int(score)} : {b['annotated']} / {b['total']}"
    score_lines.append(line)

# --- Bandeau latéral complet ---
st.sidebar.markdown(
    f"📊 Progression : {annotated_by_user} annotés par toi <br>"
    f"/ {annotated_total} au total / {total_articles} articles<br><br>"
    f"✅ Contiennent un questionnaire : {contains_questionnaire} ({contains_by_user} par toi)<br>"
    f"❌ N’en contiennent pas : {no_questionnaire} ({no_by_user} par toi)<br><br>"
    "📈 État par score :<br>" + "<br>\n".join(score_lines), unsafe_allow_html=True
)
# --- Récupération du prochain article non annoté ---
def get_next_article(user: str):
    # Récupère tous les article_id déjà annotés par cet utilisateur
    annotated_ids = [
        doc["article_id"]
        for doc in col_articles.find(
            {"annotations.annotator": user}, {"article_id": 1}
        )
    ]

    # Sélectionne un article qui n’est pas dans cette liste
    query = {"article_id": {"$nin": annotated_ids}}

    next_article = col_articles.find_one(query, sort=[("score_questionnaire", -1)])

    if next_article:
        print("➡️", next_article.get("article_id"), next_article.get("doi"))
    else:
        print(f"✅ Plus d’articles disponibles pour {user}")
    return next_article

article = get_next_article(annotator)

if not article:
    st.success("🎉 Plus d’articles à annoter !")
    st.stop()

article_id = article["article_id"]
pdf_url = article.get("pdf_url")
# --- Compteurs d'annotation ---
total_articles = col_articles.count_documents({})
annotated_by_user = col_articles.count_documents(
    {"annotations.annotator": annotator}
)
annotated_total = col_articles.count_documents(
    {"annotations": {"$exists": True, "$ne": []}}
)
contains_questionnaire = col_articles.count_documents({"annotations.decision": True})
no_questionnaire = col_articles.count_documents({"annotations.decision": False})
st.header(article["titre"])
st.caption(f"DOI: {article.get('doi')} — Année: {article.get('annee')}")
# --- Layout en 2 colonnes ---
col_meta, col_pdf = st.columns([2, 3])

with col_meta:
    st.subheader("📑 Métadonnées")
    st.write(f"**Titre** : {article.get('titre')}")
    st.write(f"**DOI** : {article.get('doi')}")
    st.write(f"**Score** : {article.get('score_questionnaire')}")
    st.write(f"**Année** : {article.get('annee')}")
    st.write(f"**Revue** : {article.get('revue')}")
    st.write(f"**pick_pdf_url** : {article.get('domain')}")
    st.write(f"**Auteurs** : {', '.join(article.get('auteurs', []))}")
    st.write(f"**Mots-clés** : {', '.join(article.get('mots_cles', []))}")
    
    st.markdown("---")
    st.sidebar.info(
        f"📊 {annotated_total} annotés "
        f"/ {total_articles} articles \n")
    st.sidebar.info(    f" oui: {contains_questionnaire} |"
        f" non : {no_questionnaire}")

    # Boutons annotation
    def save_annotation(article_id: str, decision: str | None, user: str):
        """
        decision : 'yes' / 'no' / 'skip' / 'wrong_domain'
        """
        mapping = {
            True: "yes",
            False: "no",
            None: "skip",
        }
        decision_str = mapping.get(decision, decision)  # garde 'wrong_domain' tel quel

        col_articles.update_one(
            {"article_id": article_id},
            {"$push": {
                "annotations": {
                    "annotator": user,
                    "decision": decision_str,
                    "ts": datetime.now(timezone.utc)
                }
            }}
        )

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("✅ Oui, contient un questionnaire"):
            save_annotation(article_id, True, annotator)
            st.rerun()
    with b2:
        if st.button("❌ Non, ne contient pas de questionnaire"):
            save_annotation(article_id, False, annotator)
            st.rerun()
    with b3:
        if st.button("➡️ Passer"):
            save_annotation(article_id, None, annotator)
            st.rerun()
    with b4:
        if st.button("🚫 Mauvais pick_pdf_url"):
            save_annotation(article_id, "wrong_domain", annotator)
            st.rerun()

with col_pdf:
    st.subheader("📄 Aperçu PDF")
    if pdf_url:
        pdf_viewer = f'<iframe src="{pdf_url}#zoom=page-width" width="100%" height="1200px"></iframe>'
        st.components.v1.html(pdf_viewer, height=1400)
    else:
        st.warning("Pas de PDF disponible pour cet article.")