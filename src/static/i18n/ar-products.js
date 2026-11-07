/* Arabic for the products page (products.html) (plan 038). Terms from docs/design/arabic-glossary.md.
   One JSON object per `I18n.add(...)`, read by tests/test_i18n_catalogs.py.

   The warning before a product is deleted counts what goes. Each count is a
   phrase of its own ("{n} file", "{n} files"), in the nominative, and each
   sentence takes it where Arabic reads a nominative: after a colon, or as the
   subject. "Shared", the shared memory, reads «المشتركة». The word to type is
   "تأكيد"; the page takes "confirm" too. */

I18n.add({
  "Each with its own knowledge and answers, beside what the whole team shares": "لكل منها معرفته وإجاباته، إلى جانب ما يتشاركه الفريق كله",
  "The team keeps one shared knowledge base and answer memory. A product adds its own beside them: a questionnaire answered for a product draws on the shared material and on that product’s, and one answered for “General” draws on the shared material alone.": "يحتفظ الفريق بقاعدة معرفة مشتركة واحدة وذاكرة إجابات مشتركة واحدة، ويضيف كل منتج قاعدته وذاكرته إلى جانبهما: فالاستبيان الذي يُجاب عنه لمنتج ما يستند إلى المواد المشتركة وإلى مواد ذلك المنتج، والاستبيان الذي يُجاب عنه لـ«عام» يستند إلى المواد المشتركة وحدها.",

  "Add a product": "إضافة منتج",
  "Team leads and administrators can add, rename and delete products.": "يستطيع قادة الفرق ومسؤولو النظام إضافة المنتجات وإعادة تسميتها وحذفها.",
  "The product's colour": "لون المنتج",
  "Colour": "اللون",
  "Name, for example Availo": "الاسم، مثلاً: أفايلو",
  "Name": "الاسم",
  "What it is (optional)": "ما هو (اختياري)",
  "Description": "الوصف",
  "Add": "إضافة",
  "Added {name}.": "تمت إضافة {name}.",

  "The team’s products": "منتجات الفريق",
  "Rename, recolour or delete them here.": "أعد تسميتها أو غيّر ألوانها أو احذفها من هنا.",
  "Only the team's leads and administrators can change products.": "لا يستطيع تغيير المنتجات إلا قادة الفريق ومسؤولو النظام.",
  "No products yet. Questionnaires are answered from the shared knowledge (General).": "لا توجد منتجات بعد. يُجاب عن الاستبيانات من المعرفة المشتركة (عام).",
  "Added {date}": "أُضيف في {date}",
  "Added {date} by {name}": "أضافه {name} في {date}",
  "Edit": "تعديل",
  "Delete": "حذف",
  "Save": "حفظ",
  "Cancel": "إلغاء",

  "Delete this product permanently?": "هل تريد حذف هذا المنتج نهائياً؟",
  "Delete {name} permanently?": "هل تريد حذف {name} نهائياً؟",
  "This cannot be undone. Deleting {name} removes, for the whole team:": "لا يمكن التراجع عن ذلك. حذف {name} يزيل، للفريق كله:",
  "Counting what would be deleted…": "جارٍ حصر ما سيُحذف…",
  "Could not count what would be deleted ({error}). Deleting still removes everything listed.": "تعذّر حصر ما سيُحذف ({error}). سيزيل الحذف مع ذلك كل ما ورد.",
  "To keep something, download its documents from the document library, or move answers to Shared on the Answer memory page, first.": "للاحتفاظ بشيء منه، نزّل وثائقه من مكتبة الوثائق أولاً، أو انقل الإجابات إلى «المشتركة» في صفحة ذاكرة الإجابات.",
  "Type": "اكتب",
  "confirm": "تأكيد",
  "to delete it": "لحذفه",
  "Type {word} to delete {name} and everything listed above": "اكتب {word} لحذف {name} وكل ما ورد أعلاه",
  "Delete permanently": "حذف نهائي",

  "Its knowledge base: every document, and its file on the server unless the shared knowledge base, another product or a questionnaire also uses it.": "قاعدة معرفته: كل وثيقة، وملفها على الخادم ما لم تستخدمه أيضاً قاعدة المعرفة المشتركة أو منتج آخر أو استبيان.",
  "Its knowledge base: no documents.": "قاعدة معرفته: لا وثائق.",
  "Its knowledge base: {documents} ({passages}).": "قاعدة معرفته: {documents} ({passages}).",
  "Its knowledge base: {documents} ({passages}), and its file on the server.": "قاعدة معرفته: {documents} ({passages})، وملفها على الخادم.",
  "Its knowledge base: {documents} ({passages}), and their files on the server.": "قاعدة معرفته: {documents} ({passages})، وملفاتها على الخادم.",
  "Its knowledge base: {documents} ({passages}), and {files} on the server.": "قاعدة معرفته: {documents} ({passages})، و{files} على الخادم.",
  "It leaves the document library and can no longer be opened or downloaded, even from answers that cite it.": "سيخرج من مكتبة الوثائق، ولن يمكن فتحه أو تنزيله بعد ذلك، حتى من الإجابات التي تستشهد به.",
  "They leave the document library and can no longer be opened or downloaded, even from answers that cite them.": "ستخرج من مكتبة الوثائق، ولن يمكن فتحها أو تنزيلها بعد ذلك، حتى من الإجابات التي تستشهد بها.",
  "{files} of the same name in the team's folder stays, because the shared knowledge base, another product or a questionnaire may use it.": "يبقى في مجلد الفريق {files} بالاسم نفسه، لأن قاعدة المعرفة المشتركة أو منتجاً آخر أو استبياناً قد يستخدمه.",
  "{files} of the same name in the team's folder stay, because the shared knowledge base, another product or a questionnaire may use them.": "يبقى في مجلد الفريق {files} بالاسم نفسه، لأن قاعدة المعرفة المشتركة أو منتجاً آخر أو استبياناً قد يستخدمها.",
  "{names} and {n} more": "{names}، و{n} غيرها",
  "Its answer memory: every remembered answer, including any moved here from Shared.": "ذاكرة إجاباته: كل إجابة محفوظة، بما في ذلك ما نُقل إليها من «المشتركة».",
  "Its answer memory: no remembered answers.": "ذاكرة إجاباته: لا إجابات محفوظة.",
  "Its answer memory: {answers}.": "ذاكرة إجاباته: {answers}.",
  "Its answer memory: {answers}, including {moved} moved here from Shared.": "ذاكرة إجاباته: {answers}، منها ما نُقل إليها من «المشتركة»: {moved}.",
  "It is deleted, not moved back to Shared.": "ستُحذف هذه الإجابة، ولن تُعاد إلى «المشتركة».",
  "They are deleted, not moved back to Shared.": "ستُحذف كلها، ولن تُعاد إلى «المشتركة».",
  "What stays: {questionnaires} and {chats} for {name} stay listed, marked as from a deleted product, and become read-only.": "ما يبقى: {questionnaires} و{chats} للمنتج {name}، تبقى في القوائم موسومةً بأنها من منتج محذوف، وتصبح للقراءة فقط.",
  "What stays: its questionnaires and chats stay listed, marked as from a deleted product, and become read-only.": "ما يبقى: استبياناته ومحادثاته تبقى في القوائم موسومةً بأنها من منتج محذوف، وتصبح للقراءة فقط.",
  "Their answers can be read and filled files downloaded, but nothing in them can be answered, edited, approved or chatted in again.": "يمكن قراءة إجاباتها وتنزيل الملفات المملوءة، لكن لا يمكن بعد ذلك الإجابة عن أي شيء فيها أو تعديله أو اعتماده أو المحادثة فيها.",
  "Deleted {name}: {files} and {answers} removed; {questionnaires} and {chats} are kept, read-only.": "حُذف {name}. ما أُزيل: {files} و{answers}؛ وما بقي للقراءة فقط: {questionnaires} و{chats}.",
  "{files} could not be removed from the server; see the log.": "ما تعذّرت إزالته من الخادم: {files}؛ راجع السجل.",

  "{n} document": "وثيقة واحدة",
  "{n} documents": {
    "two": "وثيقتان",
    "few": "{n} وثائق",
    "many": "{n} وثيقة",
    "other": "{n} وثيقة"
  },
  "{n} passage": "مقطع واحد",
  "{n} passages": {
    "two": "مقطعان",
    "few": "{n} مقاطع",
    "many": "{n} مقطعاً",
    "other": "{n} مقطع"
  },
  "{n} file": "ملف واحد",
  "{n} files": {
    "two": "ملفان",
    "few": "{n} ملفات",
    "many": "{n} ملفاً",
    "other": "{n} ملف"
  },
  "{n} remembered answer": "إجابة محفوظة واحدة",
  "{n} remembered answers": {
    "two": "إجابتان محفوظتان",
    "few": "{n} إجابات محفوظة",
    "many": "{n} إجابة محفوظة",
    "other": "{n} إجابة محفوظة"
  },
  "{n} questionnaire": "استبيان واحد",
  "{n} questionnaires": {
    "two": "استبيانان",
    "few": "{n} استبيانات",
    "many": "{n} استبياناً",
    "other": "{n} استبيان"
  },
  "{n} chat": "محادثة واحدة",
  "{n} chats": {
    "two": "محادثتان",
    "few": "{n} محادثات",
    "many": "{n} محادثة",
    "other": "{n} محادثة"
  },

  "Your changes on this page are not saved yet. Switch the language anyway, and lose them?": "لم تُحفظ تغييراتك في هذه الصفحة بعد. هل تريد تبديل اللغة على أي حال وفقدانها؟",
  "Request failed ({status})": "تعذّر تنفيذ الطلب ({status})"
});
