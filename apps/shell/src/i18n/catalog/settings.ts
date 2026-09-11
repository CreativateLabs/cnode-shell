// SettingsOverlay (Einstellungen: Profil, Modell, Mitglieder, Teams, Marktplatz,
// Mandanten, Promotions) + ClientSwitcher (Mandanten-/Client-Umschalter).
export default {
  de: {
    // Overlay-Navigation
    'settings.nav.profile': 'Profil',
    'settings.nav.model': 'Modell',
    'settings.nav.members': 'Mitglieder',
    'settings.nav.teams': 'Teams',
    'settings.nav.connectors': 'Marktplatz',
    'settings.nav.tenants': 'Mandanten',
    'settings.nav.promotions': 'Promotions',

    // Profil
    'settings.profile.title': 'Profil',
    'settings.profile.desc': 'Deine Identität und Standard-Modell für neue Threads.',
    'settings.profile.email': 'E-Mail',
    'settings.profile.role': 'Rolle',
    'settings.profile.tenant': 'Mandant',
    'settings.profile.default_model': 'Standard-Modell (Provider-Default)',
    'settings.profile.local_oss': 'lokal · OSS',
    'settings.profile.gemini_cloud': 'Gemini · Cloud',
    'settings.provider.gemini_title': 'Gemini (Cloud)',
    'settings.provider.gemini_missing': 'GOOGLE_API_KEY nicht gesetzt',
    'settings.provider.claude_title': 'Claude (Cloud)',
    'settings.provider.claude_missing': 'ANTHROPIC_API_KEY nicht gesetzt',

    // Rollen-Labels
    'settings.role.lead': 'Lead',
    'settings.role.member': 'Member',
    'settings.role.lead_badge': '★ Lead',

    // Teams
    'settings.teams.title': 'Teams',
    'settings.teams.desc': 'Gliedere die Organisation in Teams mit Team-Lead und Members. Ein User kann in mehreren Teams sein.',
    'settings.teams.new_label': 'Neues Team',
    'settings.teams.new_ph': 'z. B. Innovation, Vertrieb, Legal',
    'settings.teams.create': 'Anlegen',
    'settings.teams.loading': 'Lade Teams …',
    'settings.teams.empty': 'Noch keine Teams.',
    'settings.teams.delete_title': 'Team löschen',
    'settings.teams.delete_confirm': 'Team „{{name}}“ löschen?',
    'settings.teams.member_count': '{{count}} Member',
    'settings.teams.you_role': 'du: {{role}}',

    // Team-Detail
    'settings.team.member_ph': 'member@org.de',
    'settings.team.add_member': '+ Member',
    'settings.team.invite_link': 'Invite-Link',
    'settings.team.invite_sent': 'Einladung per E-Mail verschickt ✓',
    'settings.team.magic_copied': 'Magic-Link kopiert: {{link}}',
    'settings.team.toggle_role': 'Rolle wechseln',
    'settings.team.remove': 'Entfernen',
    'settings.team.loading': 'Lade Members …',
    'settings.team.empty': 'Noch keine Members.',

    // Mitglieder
    'settings.members.title': 'Mitglieder',
    'settings.members.desc': 'Lade Kolleg:innen per Magic-Link in diesen Mandanten ein.',
    'settings.members.invite_label': 'E-Mail einladen',
    'settings.members.invite_ph': 'kollege@mandant.de',
    'settings.members.invite': 'Einladen',
    'settings.members.loading': 'Lade Mitglieder …',
    'settings.members.empty': 'Noch keine Mitglieder.',
    'settings.members.remove': 'Entfernen',

    // Ingest-Quellen
    'settings.sources.title': 'Ingest-Quellen',
    'settings.sources.desc': 'Scraping-Allowlist: nur diese Domains dürfen für URL-Ingest gecrawlt werden.',
    'settings.sources.domain_label': 'Domain erlauben',
    'settings.sources.domain_ph': 'beispiel.de',
    'settings.sources.add': 'Hinzufügen',
    'settings.sources.loading': 'Lade Allowlist …',
    'settings.sources.empty': 'Noch keine Domains freigegeben.',
    'settings.sources.save': 'Allowlist speichern',
    'settings.sources.saved': 'Gespeichert.',

    // Mandanten
    'settings.tenants.title': 'Mandanten',
    'settings.tenants.desc': 'Lege Mandanten an und weise ihnen Admins zu.',
    'settings.tenants.new_label': 'Neuer Mandant',
    'settings.tenants.new_ph': 'Mandantenname',
    'settings.tenants.create': 'Anlegen',
    'settings.tenants.delete_confirm': 'Mandant wirklich löschen? Alle zugehörigen Daten bleiben isoliert entfernt.',
    'settings.tenants.assigned': 'Admin {{email}} zugewiesen.',
    'settings.tenants.loading': 'Lade Mandanten …',
    'settings.tenants.empty': 'Noch keine Mandanten.',
    'settings.tenants.delete_title': 'Löschen',
    'settings.tenants.admin_ph': 'admin@mandant.de',
    'settings.tenants.assign_admin': 'Admin zuweisen',

    // Promotions
    'settings.promotions.title': 'Promotions',
    'settings.promotions.desc': 'Von Admins vorgeschlagene Quellen für den geteilten Markt-Graphen (Market). Freigeben oder ablehnen.',
    'settings.promotions.loading': 'Lade Vorschläge …',
    'settings.promotions.empty': 'Keine offenen Vorschläge.',
    'settings.promotions.approve': 'Freigeben',
    'settings.promotions.reject': 'Ablehnen',

    // Modell & API
    'settings.model.title': 'Modell & API',
    'settings.model.desc_sandbox': 'In der Sandbox läuft c:node über Gemini — EU-gehostet, kein lokales Setup nötig.',
    'settings.model.desc': 'Wähle das Standard-Modell für neue Antworten. c:node läuft lokal-first über Ollama; Cloud-Provider werden später per API-Key freigeschaltet.',
    'settings.model.ollama_name': 'Lokal · Ollama · {{model}}',
    'settings.model.ollama_sub': 'EU-souverän, kein Cloud-Call — läuft auf deiner Maschine.',
    'settings.model.claude_sub_ready': 'Cloud — API-Key serverseitig gesetzt.',
    'settings.model.claude_sub_missing': 'Cloud — API-Key noch nicht gesetzt.',
    'settings.model.gemini_sub_sandbox': 'Cloud — EU-gehostet.',
    'settings.model.gemini_sub': 'Cloud — in Vorbereitung.',
    'settings.model.badge_soon': 'bald',
    'settings.model.badge_default': 'Standard',
    'settings.model.api_config': 'API-Konfiguration',
    'settings.model.anthropic_key': 'Anthropic API-Key',
    'settings.model.gemini_key': 'Google Gemini API-Key',
    'settings.model.note_before': 'Schlüssel werden vorerst ',
    'settings.model.note_bold': 'serverseitig',
    'settings.model.note_after': ' (Container-Env) gesetzt. Die Eingabe pro Mandant hier ist vorbereitet und wird mit der nächsten Ausbaustufe aktiv.',

    // Marktplatz (Connectors)
    'settings.connectors.title': 'Marktplatz',
    'settings.connectors.desc_admin': 'Kuratierter Marktplatz für Eingang (Ingest) und Ausgang (Output). Aktive Connectoren stehen im Mandanten zur Verfügung.',
    'settings.connectors.desc': 'Marktplatz für Eingang und Ausgang. Nur Admins können Connectoren aktivieren.',

    // ClientSwitcher
    'clientswitcher.select': 'Client wählen',
    'clientswitcher.header': 'Mandant · client_id',
    'clientswitcher.empty': 'Keine Clients geladen',
  },
  en: {
    // Overlay navigation
    'settings.nav.profile': 'Profile',
    'settings.nav.model': 'Model',
    'settings.nav.members': 'Members',
    'settings.nav.teams': 'Teams',
    'settings.nav.connectors': 'Marketplace',
    'settings.nav.tenants': 'Tenants',
    'settings.nav.promotions': 'Promotions',

    // Profile
    'settings.profile.title': 'Profile',
    'settings.profile.desc': 'Your identity and default model for new threads.',
    'settings.profile.email': 'Email',
    'settings.profile.role': 'Role',
    'settings.profile.tenant': 'Tenant',
    'settings.profile.default_model': 'Default model (provider default)',
    'settings.profile.local_oss': 'local · OSS',
    'settings.profile.gemini_cloud': 'Gemini · Cloud',
    'settings.provider.gemini_title': 'Gemini (Cloud)',
    'settings.provider.gemini_missing': 'GOOGLE_API_KEY not set',
    'settings.provider.claude_title': 'Claude (Cloud)',
    'settings.provider.claude_missing': 'ANTHROPIC_API_KEY not set',

    // Role labels
    'settings.role.lead': 'Lead',
    'settings.role.member': 'Member',
    'settings.role.lead_badge': '★ Lead',

    // Teams
    'settings.teams.title': 'Teams',
    'settings.teams.desc': 'Structure the organisation into teams with a team lead and members. A user can belong to several teams.',
    'settings.teams.new_label': 'New team',
    'settings.teams.new_ph': 'e.g. Innovation, Sales, Legal',
    'settings.teams.create': 'Create',
    'settings.teams.loading': 'Loading teams …',
    'settings.teams.empty': 'No teams yet.',
    'settings.teams.delete_title': 'Delete team',
    'settings.teams.delete_confirm': 'Delete team “{{name}}”?',
    'settings.teams.member_count': '{{count}} members',
    'settings.teams.you_role': 'you: {{role}}',

    // Team detail
    'settings.team.member_ph': 'member@org.com',
    'settings.team.add_member': '+ Member',
    'settings.team.invite_link': 'Invite link',
    'settings.team.invite_sent': 'Invitation sent by email ✓',
    'settings.team.magic_copied': 'Magic link copied: {{link}}',
    'settings.team.toggle_role': 'Change role',
    'settings.team.remove': 'Remove',
    'settings.team.loading': 'Loading members …',
    'settings.team.empty': 'No members yet.',

    // Members
    'settings.members.title': 'Members',
    'settings.members.desc': 'Invite colleagues into this tenant via magic link.',
    'settings.members.invite_label': 'Invite by email',
    'settings.members.invite_ph': 'colleague@tenant.com',
    'settings.members.invite': 'Invite',
    'settings.members.loading': 'Loading members …',
    'settings.members.empty': 'No members yet.',
    'settings.members.remove': 'Remove',

    // Ingest sources
    'settings.sources.title': 'Ingest sources',
    'settings.sources.desc': 'Scraping allowlist: only these domains may be crawled for URL ingest.',
    'settings.sources.domain_label': 'Allow domain',
    'settings.sources.domain_ph': 'example.com',
    'settings.sources.add': 'Add',
    'settings.sources.loading': 'Loading allowlist …',
    'settings.sources.empty': 'No domains allowed yet.',
    'settings.sources.save': 'Save allowlist',
    'settings.sources.saved': 'Saved.',

    // Tenants
    'settings.tenants.title': 'Tenants',
    'settings.tenants.desc': 'Create tenants and assign admins to them.',
    'settings.tenants.new_label': 'New tenant',
    'settings.tenants.new_ph': 'Tenant name',
    'settings.tenants.create': 'Create',
    'settings.tenants.delete_confirm': 'Really delete this tenant? All related data is removed in isolation.',
    'settings.tenants.assigned': 'Admin {{email}} assigned.',
    'settings.tenants.loading': 'Loading tenants …',
    'settings.tenants.empty': 'No tenants yet.',
    'settings.tenants.delete_title': 'Delete',
    'settings.tenants.admin_ph': 'admin@tenant.com',
    'settings.tenants.assign_admin': 'Assign admin',

    // Promotions
    'settings.promotions.title': 'Promotions',
    'settings.promotions.desc': 'Sources proposed by admins for the shared market graph (Market). Approve or reject.',
    'settings.promotions.loading': 'Loading proposals …',
    'settings.promotions.empty': 'No open proposals.',
    'settings.promotions.approve': 'Approve',
    'settings.promotions.reject': 'Reject',

    // Model & API
    'settings.model.title': 'Model & API',
    'settings.model.desc_sandbox': 'In the sandbox, c:node runs on Gemini — EU-hosted, no local setup required.',
    'settings.model.desc': 'Choose the default model for new answers. c:node runs local-first via Ollama; cloud providers are unlocked later via API key.',
    'settings.model.ollama_name': 'Local · Ollama · {{model}}',
    'settings.model.ollama_sub': 'EU-sovereign, no cloud call — runs on your machine.',
    'settings.model.claude_sub_ready': 'Cloud — API key set server-side.',
    'settings.model.claude_sub_missing': 'Cloud — API key not set yet.',
    'settings.model.gemini_sub_sandbox': 'Cloud — EU-hosted.',
    'settings.model.gemini_sub': 'Cloud — coming soon.',
    'settings.model.badge_soon': 'soon',
    'settings.model.badge_default': 'Default',
    'settings.model.api_config': 'API configuration',
    'settings.model.anthropic_key': 'Anthropic API key',
    'settings.model.gemini_key': 'Google Gemini API key',
    'settings.model.note_before': 'Keys are set ',
    'settings.model.note_bold': 'server-side',
    'settings.model.note_after': ' (container env) for now. Per-tenant entry here is prepared and will become active with the next build stage.',

    // Marketplace (connectors)
    'settings.connectors.title': 'Marketplace',
    'settings.connectors.desc_admin': 'Curated marketplace for inbound (ingest) and outbound (output). Active connectors are available in the tenant.',
    'settings.connectors.desc': 'Marketplace for inbound and outbound. Only admins can activate connectors.',

    // ClientSwitcher
    'clientswitcher.select': 'Select client',
    'clientswitcher.header': 'Client · client_id',
    'clientswitcher.empty': 'No clients loaded',
  },
  fr: {
    // Navigation de l’overlay
    'settings.nav.profile': 'Profil',
    'settings.nav.model': 'Modèle',
    'settings.nav.members': 'Membres',
    'settings.nav.teams': 'Équipes',
    'settings.nav.connectors': 'Place de marché',
    'settings.nav.tenants': 'Clients',
    'settings.nav.promotions': 'Promotions',

    // Profil
    'settings.profile.title': 'Profil',
    'settings.profile.desc': 'Votre identité et votre modèle par défaut pour les nouveaux fils.',
    'settings.profile.email': 'E-mail',
    'settings.profile.role': 'Rôle',
    'settings.profile.tenant': 'Client',
    'settings.profile.default_model': 'Modèle par défaut (défaut du fournisseur)',
    'settings.profile.local_oss': 'local · OSS',
    'settings.profile.gemini_cloud': 'Gemini · Cloud',
    'settings.provider.gemini_title': 'Gemini (Cloud)',
    'settings.provider.gemini_missing': 'GOOGLE_API_KEY non défini',
    'settings.provider.claude_title': 'Claude (Cloud)',
    'settings.provider.claude_missing': 'ANTHROPIC_API_KEY non défini',

    // Libellés de rôle
    'settings.role.lead': 'Lead',
    'settings.role.member': 'Membre',
    'settings.role.lead_badge': '★ Lead',

    // Équipes
    'settings.teams.title': 'Équipes',
    'settings.teams.desc': 'Structurez l’organisation en équipes avec un lead et des membres. Un utilisateur peut appartenir à plusieurs équipes.',
    'settings.teams.new_label': 'Nouvelle équipe',
    'settings.teams.new_ph': 'p. ex. Innovation, Ventes, Juridique',
    'settings.teams.create': 'Créer',
    'settings.teams.loading': 'Chargement des équipes …',
    'settings.teams.empty': 'Aucune équipe pour l’instant.',
    'settings.teams.delete_title': 'Supprimer l’équipe',
    'settings.teams.delete_confirm': 'Supprimer l’équipe « {{name}} » ?',
    'settings.teams.member_count': '{{count}} membres',
    'settings.teams.you_role': 'vous : {{role}}',

    // Détail d’équipe
    'settings.team.member_ph': 'membre@org.fr',
    'settings.team.add_member': '+ Membre',
    'settings.team.invite_link': 'Lien d’invitation',
    'settings.team.invite_sent': 'Invitation envoyée par e-mail ✓',
    'settings.team.magic_copied': 'Lien magique copié : {{link}}',
    'settings.team.toggle_role': 'Changer de rôle',
    'settings.team.remove': 'Retirer',
    'settings.team.loading': 'Chargement des membres …',
    'settings.team.empty': 'Aucun membre pour l’instant.',

    // Membres
    'settings.members.title': 'Membres',
    'settings.members.desc': 'Invitez des collègues dans ce client via un lien magique.',
    'settings.members.invite_label': 'Inviter par e-mail',
    'settings.members.invite_ph': 'collegue@client.fr',
    'settings.members.invite': 'Inviter',
    'settings.members.loading': 'Chargement des membres …',
    'settings.members.empty': 'Aucun membre pour l’instant.',
    'settings.members.remove': 'Retirer',

    // Sources d’import
    'settings.sources.title': 'Sources d’import',
    'settings.sources.desc': 'Liste d’autorisation de scraping : seuls ces domaines peuvent être explorés pour l’import d’URL.',
    'settings.sources.domain_label': 'Autoriser le domaine',
    'settings.sources.domain_ph': 'exemple.fr',
    'settings.sources.add': 'Ajouter',
    'settings.sources.loading': 'Chargement de la liste …',
    'settings.sources.empty': 'Aucun domaine autorisé pour l’instant.',
    'settings.sources.save': 'Enregistrer la liste',
    'settings.sources.saved': 'Enregistré.',

    // Clients
    'settings.tenants.title': 'Clients',
    'settings.tenants.desc': 'Créez des clients et assignez-leur des admins.',
    'settings.tenants.new_label': 'Nouveau client',
    'settings.tenants.new_ph': 'Nom du client',
    'settings.tenants.create': 'Créer',
    'settings.tenants.delete_confirm': 'Supprimer vraiment ce client ? Toutes les données associées sont supprimées de façon isolée.',
    'settings.tenants.assigned': 'Admin {{email}} assigné.',
    'settings.tenants.loading': 'Chargement des clients …',
    'settings.tenants.empty': 'Aucun client pour l’instant.',
    'settings.tenants.delete_title': 'Supprimer',
    'settings.tenants.admin_ph': 'admin@client.fr',
    'settings.tenants.assign_admin': 'Assigner un admin',

    // Promotions
    'settings.promotions.title': 'Promotions',
    'settings.promotions.desc': 'Sources proposées par les admins pour le graphe de marché partagé (Market). Approuver ou refuser.',
    'settings.promotions.loading': 'Chargement des propositions …',
    'settings.promotions.empty': 'Aucune proposition ouverte.',
    'settings.promotions.approve': 'Approuver',
    'settings.promotions.reject': 'Refuser',

    // Modèle & API
    'settings.model.title': 'Modèle & API',
    'settings.model.desc_sandbox': 'Dans le bac à sable, c:node fonctionne via Gemini — hébergé en UE, aucune configuration locale requise.',
    'settings.model.desc': 'Choisissez le modèle par défaut pour les nouvelles réponses. c:node fonctionne en local d’abord via Ollama ; les fournisseurs cloud sont débloqués plus tard via une clé API.',
    'settings.model.ollama_name': 'Local · Ollama · {{model}}',
    'settings.model.ollama_sub': 'Souverain UE, aucun appel cloud — fonctionne sur votre machine.',
    'settings.model.claude_sub_ready': 'Cloud — clé API définie côté serveur.',
    'settings.model.claude_sub_missing': 'Cloud — clé API pas encore définie.',
    'settings.model.gemini_sub_sandbox': 'Cloud — hébergé en UE.',
    'settings.model.gemini_sub': 'Cloud — bientôt disponible.',
    'settings.model.badge_soon': 'bientôt',
    'settings.model.badge_default': 'Par défaut',
    'settings.model.api_config': 'Configuration API',
    'settings.model.anthropic_key': 'Clé API Anthropic',
    'settings.model.gemini_key': 'Clé API Google Gemini',
    'settings.model.note_before': 'Les clés sont définies ',
    'settings.model.note_bold': 'côté serveur',
    'settings.model.note_after': ' (env du conteneur) pour l’instant. La saisie par client ici est préparée et deviendra active avec la prochaine étape.',

    // Place de marché (connecteurs)
    'settings.connectors.title': 'Place de marché',
    'settings.connectors.desc_admin': 'Place de marché curatée pour l’entrée (import) et la sortie (export). Les connecteurs actifs sont disponibles dans le client.',
    'settings.connectors.desc': 'Place de marché pour l’entrée et la sortie. Seuls les admins peuvent activer des connecteurs.',

    // ClientSwitcher
    'clientswitcher.select': 'Choisir un client',
    'clientswitcher.header': 'Client · client_id',
    'clientswitcher.empty': 'Aucun client chargé',
  },
}
