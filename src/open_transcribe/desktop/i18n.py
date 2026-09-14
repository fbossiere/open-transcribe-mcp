"""User-visible strings in English and French.

Every entry is a whole sentence or label with named placeholders. Translated text is never built
by concatenating fragments, because word order is not the same in both languages. The keys are
stable technical identifiers and never appear in the interface.
"""

import os
from collections.abc import Mapping
from typing import Any

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "fr")

_CATALOGUE: dict[str, dict[str, str]] = {
    "en": {
        "app.name": "OpenTranscribe Setup",
        "app.tagline": "Own the recorder. Choose the intelligence.",
        "nav.back": "Back",
        "nav.cancel": "Cancel",
        "nav.continue": "Continue",
        "nav.details": "Details",
        "nav.step": "Step {current} of {total}",
        "nav.close": "Close",
        # Step 1 — Welcome
        "welcome.title": "Connect OpenTranscribe to your assistant",
        "welcome.body": (
            "OpenTranscribe runs on this computer and sends audio to the transcription provider "
            "you choose. The transcript is returned to your assistant. If your assistant uses a "
            "cloud model, its provider may also process the transcript. OpenTranscribe does not "
            "keep a transcript history by default."
        ),
        "welcome.no_account": (
            "No OpenTranscribe account is needed. You bring your own provider key."
        ),
        "welcome.action": "Get started",
        # Step 2 — Check this computer
        "checks.title": "Check this computer",
        "checks.subtitle": "These are the things setup needs before it can continue.",
        "checks.optional": "Optional. Setup can continue without it.",
        # Step 3 — Provider
        "provider.title": "Choose a transcription provider",
        "provider.subtitle": "Your audio is sent to the provider you choose here.",
        "provider.choose": "Choose a provider…",
        "provider.api_key": "API key",
        "provider.api_key.help": "Paste the key from your provider account.",
        "provider.reveal": "Show key",
        "provider.open_console": "Open the provider's website",
        "provider.microsoft.endpoint": "Resource endpoint",
        "provider.microsoft.endpoint.help": "The HTTPS endpoint of your speech resource.",
        "provider.microsoft.api_version": "API version",
        "provider.microsoft.no_check": (
            "This provider has no safe check that avoids transcribing, so the key is saved "
            "without being tested."
        ),
        "provider.state.available": "Available to configure",
        "provider.state.configured": "Configured",
        "provider.state.checked": "Checked",
        "provider.state.attention": "Requires attention",
        "provider.pricing": "Price as published on {date}. Estimates only.",
        "provider.pricing.unknown": "No published price is available for this model.",
        "provider.diarization": (
            "Speaker labels are anonymous, such as “Speaker 1”. Nobody is identified."
        ),
        "provider.languages.dynamic": (
            "Languages are decided by the provider and cannot be listed here."
        ),
        "provider.unknown": "Unknown",
        "provider.relay_warning": (
            "This model needs the audio itself, so OpenTranscribe must write a temporary copy on "
            "this computer. You will be asked to allow that."
        ),
        # Checks
        "check.passed": "The provider accepted this key.",
        "check.not_supported": "Key saved — transcription not tested.",
        "check.rejected": "The provider rejected this key.",
        "check.rate_limited": "The provider is rate limiting this key right now.",
        "check.quota": "The provider reports a billing or quota problem with this account.",
        "check.redirected": "The provider endpoint redirected elsewhere, so the key was not sent.",
        "check.unreachable": "The provider could not be reached.",
        "check.unavailable": "The provider returned an error.",
        # Step 4 — Client
        "client.title": "Connect your assistant",
        "client.subtitle": "Nothing is changed in your assistant until you review the setup.",
        "client.untested": (
            "This build has not been tested with {client}. OpenTranscribe will register the "
            "server and then read it back to confirm."
        ),
        "client.manual": "Add these settings to your assistant yourself.",
        "client.conflict": (
            "{client} already has a server named {name} that OpenTranscribe did not create."
        ),
        "client.takeover": "Replace that entry with this OpenTranscribe connection",
        "client.action": "Review setup",
        # Step 5 — Review
        "review.title": "Review your connection",
        "review.provider": "Transcription provider",
        "review.assistant": "Your assistant",
        "review.fallback": "Provider fallback",
        "review.history": "Transcript history",
        "review.temporary_audio": "Temporary audio processing",
        "review.keys": "Keys",
        "review.keys.value": "Stored in your session keyring",
        "review.flow": (
            "Audio is processed by the provider above. Your assistant receives the resulting "
            "transcript."
        ),
        "review.passthrough": (
            "The provider receives the source URL, including any temporary access token it "
            "contains."
        ),
        "review.relay": (
            "OpenTranscribe downloads the audio to a temporary file on this computer, sends it "
            "to the provider, and deletes it. Files expire after at most {minutes} minutes."
        ),
        "review.recipients": "Audio may be sent to: {providers}.",
        "review.changes": "Details of changes",
        "review.action": "Enable connection",
        "review.on": "On",
        "review.off": "Off",
        # Step 6 — Check and start
        "finish.title": "Check and start",
        "finish.engine_ready": "The OpenTranscribe engine answered and offers its five tools.",
        "finish.engine_failed": "The OpenTranscribe engine did not answer as expected.",
        "finish.registered": "Registered in {client}.",
        "finish.restart": "Restart {client} so it loads the new server.",
        "finish.unverified": "Connection saved — check it in your assistant.",
        "finish.confirm": "I checked it, and it works",
        "finish.prompt_label": "Copy this first prompt",
        "finish.prompt": "List the transcription models OpenTranscribe has available.",
        "finish.copy": "Copy",
        "finish.copied": "Copied.",
        "finish.action": "Finish",
        # Sample
        "sample.title": "Transcribe the public sample",
        "sample.description": (
            "A 22-second synthetic recording made by the project. Two artificial voices alternate "
            "English and French. No real person is recorded."
        ),
        "sample.cost": "Estimated cost: {amount} USD, from prices published on {date}.",
        "sample.cost.unknown": "No price is published for this model, so the cost is unknown. "
        "This check is not free.",
        "sample.run": "Transcribe the public sample",
        "sample.skip": "Skip this",
        "sample.not_tested": "Transcription not tested.",
        "sample.cancelled": (
            "The request was cancelled here. The provider may already be processing it and may "
            "still bill it."
        ),
        "sample.error.authentication": "The provider rejected the saved key.",
        "sample.error.model_access": "This account does not have access to that model.",
        "sample.error.capability": "That model cannot do what was asked of it.",
        "sample.error.quota": "The provider reports a quota or rate limit for this account.",
        "sample.error.cost": "The request was stopped by your estimated cost threshold.",
        "sample.error.source": "The sample audio could not be reached.",
        "sample.error.provider_temporary": "The provider is temporarily unavailable.",
        "sample.error.not_enabled": "That provider is not enabled for this installation.",
        "sample.error.relay_not_permitted": (
            "That model needs the audio itself, and temporary audio processing is off."
        ),
        "sample.error.unknown": "The sample could not be transcribed.",
        # Privacy and cost
        "privacy.title": "Privacy",
        "privacy.temporary_audio": "Allow temporary audio files on this computer",
        "privacy.temporary_audio.help": (
            "Needed only for models that cannot fetch a URL themselves. Files are private, expire "
            "after at most {minutes} minutes, and are deleted when a transcription ends."
        ),
        "privacy.temporary_audio.caveat": (
            "Deleting a file is not a guarantee of erasure from swap, backups, or the drive "
            "itself. A suspended computer cannot promise erasure on a clock."
        ),
        "privacy.fallback": "Allow a second provider to receive the audio if the first fails",
        "privacy.fallback.help": (
            "Off by default. When on, a failed request may already have reached the first "
            "provider before the second one is tried."
        ),
        "privacy.history": (
            "Transcript history is off. Transcripts are returned to your assistant only."
        ),
        "cost.threshold": "Estimated cost threshold",
        "cost.threshold.help": (
            "This is not a billing cap. Checks depend on available duration and pricing "
            "information."
        ),
        "cost.threshold.unavailable": "No enforceable estimate is available for this request.",
        # Status page
        "status.title": "OpenTranscribe",
        "status.check": "Check connection",
        "status.providers": "Manage providers",
        "status.repair": "Repair connection",
        "status.diagnostic": "Copy diagnostic",
        "status.updates": "Check for updates",
        "status.disconnect": "Disconnect",
        "status.last_checked": "Last checked {when}.",
        "status.never_checked": "Not checked yet.",
        "status.stale": "This was true when it was last checked, not now.",
        "status.erase": "Also erase the saved setup, including keys",
        "status.erase.confirm": (
            "This erases the saved provider settings and removes the keys OpenTranscribe stored "
            "in your keyring. It does not revoke the keys at your provider."
        ),
        "status.revocation": (
            "Removing OpenTranscribe does not revoke an API key. To revoke it, use your "
            "provider's website and restart your assistant."
        ),
        "diagnostic.preview": "This is everything that will be copied.",
        # Errors
        "error.keyring_unavailable": "Your session keyring is not available.",
        "error.keyring_locked": "Your session keyring is locked.",
        "error.config_invalid": "The saved setup could not be read.",
        "error.engine_missing": "The packaged engine is missing.",
        "error.generic": "Something went wrong.",
        "busy.checking_key": "Checking the key with the provider…",
        "busy.verifying_engine": "Starting the engine and checking its tools…",
        "busy.registering": "Registering the server in your assistant…",
        "busy.transcribing": "Transcribing the public sample…",
    },
    "fr": {
        "app.name": "Configuration d'OpenTranscribe",
        "app.tagline": "Gardez l'enregistreur. Choisissez l'intelligence.",
        "nav.back": "Retour",
        "nav.cancel": "Annuler",
        "nav.continue": "Continuer",
        "nav.details": "Détails",
        "nav.step": "Étape {current} sur {total}",
        "nav.close": "Fermer",
        "welcome.title": "Connecter OpenTranscribe à votre assistant",
        "welcome.body": (
            "OpenTranscribe s'exécute sur cet ordinateur et envoie l'audio au fournisseur de "
            "transcription que vous choisissez. La transcription est renvoyée à votre assistant. "
            "Si votre assistant utilise un modèle en ligne, son fournisseur peut lui aussi "
            "traiter la transcription. OpenTranscribe ne conserve pas d'historique des "
            "transcriptions par défaut."
        ),
        "welcome.no_account": (
            "Aucun compte OpenTranscribe n'est nécessaire. Vous utilisez votre propre clé."
        ),
        "welcome.action": "Commencer",
        "checks.title": "Vérifier cet ordinateur",
        "checks.subtitle": "Voici ce dont la configuration a besoin pour continuer.",
        "checks.optional": "Facultatif. La configuration peut continuer sans cela.",
        "provider.title": "Choisir un fournisseur de transcription",
        "provider.subtitle": "Votre audio est envoyé au fournisseur choisi ici.",
        "provider.choose": "Choisir un fournisseur…",
        "provider.api_key": "Clé d'API",
        "provider.api_key.help": "Collez la clé fournie par votre compte fournisseur.",
        "provider.reveal": "Afficher la clé",
        "provider.open_console": "Ouvrir le site du fournisseur",
        "provider.microsoft.endpoint": "Point de terminaison de la ressource",
        "provider.microsoft.endpoint.help": "Le point de terminaison HTTPS de votre ressource.",
        "provider.microsoft.api_version": "Version de l'API",
        "provider.microsoft.no_check": (
            "Ce fournisseur n'offre pas de vérification sûre sans transcrire : la clé est "
            "enregistrée sans être testée."
        ),
        "provider.state.available": "Configurable",
        "provider.state.configured": "Configuré",
        "provider.state.checked": "Vérifié",
        "provider.state.attention": "Demande votre attention",
        "provider.pricing": "Tarif publié le {date}. Estimations uniquement.",
        "provider.pricing.unknown": "Aucun tarif publié n'est disponible pour ce modèle.",
        "provider.diarization": (
            "Les étiquettes de locuteur sont anonymes, par exemple « Locuteur 1 ». Personne "
            "n'est identifié."
        ),
        "provider.languages.dynamic": (
            "Les langues sont déterminées par le fournisseur et ne peuvent pas être listées ici."
        ),
        "provider.unknown": "Inconnu",
        "provider.relay_warning": (
            "Ce modèle a besoin de l'audio lui-même : OpenTranscribe doit écrire une copie "
            "temporaire sur cet ordinateur. Votre autorisation vous sera demandée."
        ),
        "check.passed": "Le fournisseur a accepté cette clé.",
        "check.not_supported": "Clé enregistrée — transcription non testée.",
        "check.rejected": "Le fournisseur a refusé cette clé.",
        "check.rate_limited": "Le fournisseur limite actuellement cette clé.",
        "check.quota": "Le fournisseur signale un problème de facturation ou de quota.",
        "check.redirected": (
            "Le point de terminaison a redirigé ailleurs : la clé n'a pas été envoyée."
        ),
        "check.unreachable": "Le fournisseur n'a pas pu être contacté.",
        "check.unavailable": "Le fournisseur a renvoyé une erreur.",
        "client.title": "Connecter votre assistant",
        "client.subtitle": "Rien n'est modifié tant que vous n'avez pas validé la configuration.",
        "client.untested": (
            "Cette version n'a pas été testée avec {client}. OpenTranscribe enregistrera le "
            "serveur puis le relira pour confirmer."
        ),
        "client.manual": "Ajoutez vous-même ces paramètres dans votre assistant.",
        "client.conflict": (
            "{client} possède déjà un serveur nommé {name} qu'OpenTranscribe n'a pas créé."
        ),
        "client.takeover": "Remplacer cette entrée par la connexion OpenTranscribe",
        "client.action": "Vérifier la configuration",
        "review.title": "Vérifier votre connexion",
        "review.provider": "Fournisseur de transcription",
        "review.assistant": "Votre assistant",
        "review.fallback": "Report sur un autre fournisseur",
        "review.history": "Historique des transcriptions",
        "review.temporary_audio": "Traitement audio temporaire",
        "review.keys": "Clés",
        "review.keys.value": "Enregistrées dans le trousseau de votre session",
        "review.flow": (
            "L'audio est traité par le fournisseur ci-dessus. Votre assistant reçoit la "
            "transcription obtenue."
        ),
        "review.passthrough": (
            "Le fournisseur reçoit l'URL source, y compris tout jeton d'accès temporaire qu'elle "
            "contient."
        ),
        "review.relay": (
            "OpenTranscribe télécharge l'audio dans un fichier temporaire sur cet ordinateur, "
            "l'envoie au fournisseur, puis le supprime. Ces fichiers expirent au bout de "
            "{minutes} minutes au plus."
        ),
        "review.recipients": "L'audio peut être envoyé à : {providers}.",
        "review.changes": "Détail des modifications",
        "review.action": "Activer la connexion",
        "review.on": "Activé",
        "review.off": "Désactivé",
        "finish.title": "Vérifier et démarrer",
        "finish.engine_ready": "Le moteur OpenTranscribe a répondu et propose ses cinq outils.",
        "finish.engine_failed": "Le moteur OpenTranscribe n'a pas répondu comme prévu.",
        "finish.registered": "Enregistré dans {client}.",
        "finish.restart": "Redémarrez {client} pour qu'il charge le nouveau serveur.",
        "finish.unverified": "Connexion enregistrée — vérifiez-la dans votre assistant.",
        "finish.confirm": "J'ai vérifié, cela fonctionne",
        "finish.prompt_label": "Copier cette première question",
        "finish.prompt": "Liste les modèles de transcription disponibles dans OpenTranscribe.",
        "finish.copy": "Copier",
        "finish.copied": "Copié.",
        "finish.action": "Terminer",
        "sample.title": "Transcrire l'exemple public",
        "sample.description": (
            "Un enregistrement synthétique de 22 secondes réalisé par le projet. Deux voix "
            "artificielles alternent l'anglais et le français. Aucune personne réelle n'est "
            "enregistrée."
        ),
        "sample.cost": "Coût estimé : {amount} USD, d'après les tarifs publiés le {date}.",
        "sample.cost.unknown": (
            "Aucun tarif n'est publié pour ce modèle : le coût est inconnu. Cette vérification "
            "n'est pas gratuite."
        ),
        "sample.run": "Transcrire l'exemple public",
        "sample.skip": "Passer",
        "sample.not_tested": "Transcription non testée.",
        "sample.cancelled": (
            "La demande a été annulée ici. Le fournisseur peut déjà la traiter et la facturer."
        ),
        "sample.error.authentication": "Le fournisseur a refusé la clé enregistrée.",
        "sample.error.model_access": "Ce compte n'a pas accès à ce modèle.",
        "sample.error.capability": "Ce modèle ne peut pas faire ce qui lui a été demandé.",
        "sample.error.quota": "Le fournisseur signale un quota ou une limite pour ce compte.",
        "sample.error.cost": "La demande a été arrêtée par votre seuil de coût estimé.",
        "sample.error.source": "L'audio d'exemple n'a pas pu être atteint.",
        "sample.error.provider_temporary": "Le fournisseur est temporairement indisponible.",
        "sample.error.not_enabled": "Ce fournisseur n'est pas activé pour cette installation.",
        "sample.error.relay_not_permitted": (
            "Ce modèle a besoin de l'audio lui-même, et le traitement audio temporaire est "
            "désactivé."
        ),
        "sample.error.unknown": "L'exemple n'a pas pu être transcrit.",
        "privacy.title": "Confidentialité",
        "privacy.temporary_audio": "Autoriser des fichiers audio temporaires sur cet ordinateur",
        "privacy.temporary_audio.help": (
            "Nécessaire uniquement pour les modèles qui ne peuvent pas récupérer une URL "
            "eux-mêmes. Les fichiers sont privés, expirent au bout de {minutes} minutes au plus "
            "et sont supprimés à la fin d'une transcription."
        ),
        "privacy.temporary_audio.caveat": (
            "Supprimer un fichier ne garantit pas son effacement du fichier d'échange, des "
            "sauvegardes ou du disque. Un ordinateur en veille ne peut rien promettre à l'heure."
        ),
        "privacy.fallback": (
            "Autoriser un second fournisseur à recevoir l'audio si le premier échoue"
        ),
        "privacy.fallback.help": (
            "Désactivé par défaut. Une fois activé, une demande échouée peut déjà avoir atteint "
            "le premier fournisseur avant l'essai du second."
        ),
        "privacy.history": (
            "L'historique des transcriptions est désactivé. Les transcriptions ne vont qu'à "
            "votre assistant."
        ),
        "cost.threshold": "Seuil de coût estimé",
        "cost.threshold.help": (
            "Ce n'est pas un plafond de facturation. Les vérifications dépendent de la durée et "
            "des tarifs disponibles."
        ),
        "cost.threshold.unavailable": "Aucune estimation applicable n'est disponible ici.",
        "status.title": "OpenTranscribe",
        "status.check": "Vérifier la connexion",
        "status.providers": "Gérer les fournisseurs",
        "status.repair": "Réparer la connexion",
        "status.diagnostic": "Copier le diagnostic",
        "status.updates": "Rechercher des mises à jour",
        "status.disconnect": "Déconnecter",
        "status.last_checked": "Dernière vérification : {when}.",
        "status.never_checked": "Pas encore vérifié.",
        "status.stale": "C'était vrai lors de la dernière vérification, pas maintenant.",
        "status.erase": "Effacer aussi la configuration enregistrée, y compris les clés",
        "status.erase.confirm": (
            "Ceci efface les paramètres de fournisseur enregistrés et supprime les clés "
            "qu'OpenTranscribe a placées dans votre trousseau. Cela ne révoque pas les clés chez "
            "votre fournisseur."
        ),
        "status.revocation": (
            "Désinstaller OpenTranscribe ne révoque pas une clé d'API. Pour la révoquer, "
            "utilisez le site de votre fournisseur et redémarrez votre assistant."
        ),
        "diagnostic.preview": "Voici tout ce qui sera copié.",
        "error.keyring_unavailable": "Le trousseau de votre session n'est pas disponible.",
        "error.keyring_locked": "Le trousseau de votre session est verrouillé.",
        "error.config_invalid": "La configuration enregistrée n'a pas pu être lue.",
        "error.engine_missing": "Le moteur fourni est introuvable.",
        "error.generic": "Une erreur est survenue.",
        "busy.checking_key": "Vérification de la clé auprès du fournisseur…",
        "busy.verifying_engine": "Démarrage du moteur et vérification de ses outils…",
        "busy.registering": "Enregistrement du serveur dans votre assistant…",
        "busy.transcribing": "Transcription de l'exemple public…",
    },
}


class Translator:
    """Resolves a key in the active locale, falling back to English for a missing entry."""

    def __init__(self, locale: str = DEFAULT_LOCALE) -> None:
        self.locale = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE

    def __call__(self, key: str, /, **values: Any) -> str:
        template = _CATALOGUE[self.locale].get(key) or _CATALOGUE[DEFAULT_LOCALE].get(key)
        if template is None:
            # A missing key is a bug, not something to show a user a blank label for.
            return key
        try:
            return template.format(**values)
        except (KeyError, IndexError):
            return template


def resolve_locale(preference: str = "system", environ: Mapping[str, str] | None = None) -> str:
    """Use the session locale, with an explicit override always winning."""
    if preference in SUPPORTED_LOCALES:
        return preference
    env = environ if environ is not None else os.environ
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(name, "")
        code = value.split(".", 1)[0].split("_", 1)[0].lower()
        if code in SUPPORTED_LOCALES:
            return code
    return DEFAULT_LOCALE


def translator(preference: str = "system", environ: Mapping[str, str] | None = None) -> Translator:
    return Translator(resolve_locale(preference, environ))
