/* Arabic for the server's sentences a page shows: errors by their code, why an answer is held back, the review's reasons (plan 038). Terms from docs/design/arabic-glossary.md.
   One JSON object per `I18n.add(...)`, read by tests/test_i18n_catalogs.py.

   The server keeps writing English (plan 038's decision log), so each sentence
   is matched here as it comes:
   - a fixed sentence by its whole text (`I18n.add`);
   - one the server fills in (an f-string) by a pattern (`I18n.addPatterns`),
     anchored ^...$, whose capture keeps what the case put in it: a file's or
     a product's name, clause numbers, the drafter's or the reviewer's own words;
   - an error the page has no sentence for, by its code: "error.<code>", what
     kind of problem it is (`I18n.error`).
   A pattern whose Arabic depends on a count, or on sentences inside it, is a
   function (String.replace takes one), and reads its words from the entries here. */

I18n.add({
  "holds only part of a split source; the set may be incomplete": "لا تتضمن إلا جزءاً من مصدر مقسَّم، فقد تكون المجموعة ناقصة",
  "nothing in our documents backs this — it rests only on what we told somebody before": "لا شيء في وثائقنا يدعم هذا — فهو يستند فقط إلى ما قلناه لأحدٍ من قبل",
  "the reviewer did not find the answer grounded": "لم يجد الفحص الآلي أن الإجابة مستندة إلى مصادرها",

  "it could not be answered": "تعذّرت الإجابة عن السؤال",
  "flagged for review -- {reasons}": "عُلِّمت للمراجعة — {reasons}",
  "the reviewer flagged it": "علّمها الفحص الآلي للمراجعة",
  "approved by a reviewer": "اعتمدها مراجِع",
  "written by hand": "كتبها شخص بنفسه",
  "left blank on purpose": "تُركت فارغة عن قصد",

  "Nothing in the knowledge base matched this question, so the answer is not backed by any of your documents. Treat it as unanswered and check with the team that owns this control.": "لم يطابق هذا السؤالَ أيُّ شيء في قاعدة المعرفة، لذا فالإجابة غير مدعومة بأي من وثائقكم. تعامل معها على أنها بلا إجابة، وراجِع الفريق المسؤول عن هذا الضابط.",
  "The sources touch on this subject but none of them answers the question directly, so the answer is built from the closest material available. It may be that your documents genuinely do not cover this.": "تتناول المصادر هذا الموضوع، لكن أياً منها لا يجيب عن السؤال مباشرة، لذا بُنيت الإجابة من أقرب ما هو متاح. وقد لا تغطي وثائقكم هذا الأمر فعلاً.",
  "No single clause states this outright, so the answer was inferred by combining related material from {n} source(s). The reasoning is sound but worth a second pair of eyes.": {
    "zero": "لا ينص أي بند منفرد على هذا صراحةً، لذا استُنتجت الإجابة بالجمع بين مواد ذات صلة. التعليل سليم، لكنه يستحق نظرة ثانية.",
    "one": "لا ينص أي بند منفرد على هذا صراحةً، لذا استُنتجت الإجابة بالجمع بين مواد ذات صلة من مصدر واحد. التعليل سليم، لكنه يستحق نظرة ثانية.",
    "two": "لا ينص أي بند منفرد على هذا صراحةً، لذا استُنتجت الإجابة بالجمع بين مواد ذات صلة من مصدرين. التعليل سليم، لكنه يستحق نظرة ثانية.",
    "few": "لا ينص أي بند منفرد على هذا صراحةً، لذا استُنتجت الإجابة بالجمع بين مواد ذات صلة من {n} مصادر. التعليل سليم، لكنه يستحق نظرة ثانية.",
    "many": "لا ينص أي بند منفرد على هذا صراحةً، لذا استُنتجت الإجابة بالجمع بين مواد ذات صلة من {n} مصدراً. التعليل سليم، لكنه يستحق نظرة ثانية.",
    "other": "لا ينص أي بند منفرد على هذا صراحةً، لذا استُنتجت الإجابة بالجمع بين مواد ذات صلة من {n} مصدر. التعليل سليم، لكنه يستحق نظرة ثانية."
  },
  "A second model read the answer against the sources and could not trace every statement in it back to them. \nVerify each claim against the {n} cited source(s) before submitting.": {
    "zero": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. \nتحقّق من كل ادعاء مقابل المصادر المستشهد بها قبل الإرسال.",
    "one": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. \nتحقّق من كل ادعاء مقابل المصدر المستشهد به قبل الإرسال.",
    "two": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. \nتحقّق من كل ادعاء مقابل المصدرين المستشهد بهما قبل الإرسال.",
    "few": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. \nتحقّق من كل ادعاء مقابل المصادر الـ{n} المستشهد بها قبل الإرسال.",
    "many": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. \nتحقّق من كل ادعاء مقابل المصادر الـ{n} المستشهد بها قبل الإرسال.",
    "other": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. \nتحقّق من كل ادعاء مقابل المصادر الـ{n} المستشهد بها قبل الإرسال."
  },
  "A second model read the answer against the sources and could not trace every statement in it back to them. The reviewer's note:\n {note}. \nVerify each claim against the {n} cited source(s) before submitting.": {
    "zero": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. ملاحظة الفحص الآلي:\n {note}. \nتحقّق من كل ادعاء مقابل المصادر المستشهد بها قبل الإرسال.",
    "one": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. ملاحظة الفحص الآلي:\n {note}. \nتحقّق من كل ادعاء مقابل المصدر المستشهد به قبل الإرسال.",
    "two": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. ملاحظة الفحص الآلي:\n {note}. \nتحقّق من كل ادعاء مقابل المصدرين المستشهد بهما قبل الإرسال.",
    "few": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. ملاحظة الفحص الآلي:\n {note}. \nتحقّق من كل ادعاء مقابل المصادر الـ{n} المستشهد بها قبل الإرسال.",
    "many": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. ملاحظة الفحص الآلي:\n {note}. \nتحقّق من كل ادعاء مقابل المصادر الـ{n} المستشهد بها قبل الإرسال.",
    "other": "قرأ نموذج ثانٍ الإجابة مقابل المصادر، ولم يتمكن من ردّ كل عبارة فيها إليها. ملاحظة الفحص الآلي:\n {note}. \nتحقّق من كل ادعاء مقابل المصادر الـ{n} المستشهد بها قبل الإرسال."
  },

  "Auditor detail": "تفاصيل للمدقق",
  "For an auditor checking evidence: every specific kept, each tied to its policy.": "لمدقق يتحقق من الأدلة: تُحفظ كل التفاصيل، ويُربط كلٌّ منها بسياسته.",
  "Plain language": "لغة بسيطة",
  "For a customer who is not a security specialist.": "لعميل ليس متخصصاً في الأمن.",
  "Executive summary": "ملخص تنفيذي",
  "Two sentences for a senior reader: the position, and why.": "جملتان لقارئ في منصب قيادي: الموقف، وسببه.",
  "Bullet points": "نقاط موجزة",
  "For process questions: the verdict, then one line per control.": "لأسئلة الإجراءات: الحكم أولاً، ثم سطر لكل ضابط.",

  "error.invalid_request": "تعذّر تنفيذ الطلب كما هو. راجِع ما أدخلته ثم حاول مجدداً.",
  "error.not_a_document": "هذا ليس وثيقة سياسات، فلا يمكن إزالته بهذه الطريقة.",
  "error.not_allowed": "لا يُسمح لك بتنفيذ هذا الإجراء الإداري.",
  "error.preference_invalid": "تعذّر حفظ هذا التفضيل أو هذه المهارة كما هي. راجِع القيم ثم حاول مجدداً.",
  "error.operation_refused": "تعذّر تنفيذ هذه العملية.",
  "error.questionnaire_type_unsupported": "هذا الملف ليس استبياناً بصيغة يمكن قراءتها. استخدم ملف Excel أو Word.",
  "error.sign_in_required": "سجّل الدخول للمتابعة.",
  "error.forbidden": "ليست لديك صلاحية للقيام بهذا.",
  "error.access_denied": "رُفض تسجيل الدخول. تحقّق من بريدك الإلكتروني ورمز الدخول.",
  "error.not_found": "لم يُعثر على ما طلبته. ربما حُذف.",
  "error.product_not_found": "لا يوجد منتج كهذا في هذا الفريق.",
  "error.questionnaire_not_found": "لم يُعثر على هذا الاستبيان. ربما أُغلق أو حُذف.",
  "error.conflict": "يتعارض هذا الطلب مع شيء موجود، كاسمٍ مستخدم من قبل.",
  "error.product_deleted": "حُذف هذا المنتج، فعمله محفوظ للقراءة فقط ولا يمكن تغييره.",
  "error.product_locked": "منتج الاستبيان أو المحادثة ثابت بعد اختياره.",
  "error.product_name_taken": "لدى الفريق منتج بهذا الاسم بالفعل.",
  "error.questionnaire_busy": "يُجاب عن هذا الاستبيان الآن. انتظر حتى ينتهي ثم حاول مجدداً.",
  "error.unsupported_file": "لا يمكن قبول ملف من هذا النوع.",
  "error.unprocessable": "فُهم الطلب، لكن تعذّر استخدام ما أُرسل، كملف لا يمكن قراءته.",
  "error.questionnaire_unreadable": "تعذّرت قراءة هذا الملف كمصنَّف Excel.",
  "error.nothing_to_fill": "هذه قائمة أسئلة بلا ملف تُكتب فيه الإجابات. نزّل الإجابات بدلاً من ذلك.",
  "error.document_unreadable": "تعذّرت قراءة هذا النوع من الملفات.",
  "error.internal_error": "حدث خطأ غير متوقع. حاول مجدداً، وإن تكرر فأبلغ مسؤول النظام.",
  "error.unavailable": "خدمة يعتمد عليها هذا الإجراء غير متاحة الآن، كالنموذج أو أداة التحويل. حاول لاحقاً.",
  "error.export_unavailable": "تعذّر إنشاء ملف PDF.",
  "error.admin_required": "يتطلب هذا صلاحية مسؤول النظام.",
  "error.phoenix_sign_in_required": "سجّل الدخول بحساب مسؤول نظام لعرض أداة التتبّع.",
  "error.phoenix_unavailable": "أداة التتبّع غير متاحة الآن. حاول لاحقاً.",
  "error.assistant_unconfigured": "لم يُضبط نموذج للمساعد.",
  "error.authority_invalid": "يجب أن تكون الوثيقة إما وثيقتنا أو متطلباً خارجياً.",
  "error.confirmation_required": "اكتب كلمة التأكيد لحذف المنتج.",
  "error.conversation_busy": "لا تزال هذه المحادثة تعمل على رسالتك الأخيرة. انتظر حتى تنتهي ثم حاول مجدداً.",
  "error.conversation_not_found": "لم تعد هذه المحادثة موجودة.",
  "error.document_not_found": "لم يُعثر على الوثيقة.",
  "error.document_path_invalid": "اسم الوثيقة أو موقعها غير صالح.",
  "error.document_type_unsupported": "نوع هذه الوثيقة غير مدعوم. ارفع ملف PDF أو Word.",
  "error.extraction_failed": "تعذّر استخراج النص من الوثيقة.",
  "error.filled_file_missing": "املأ الاستبيان أولاً.",
  "error.language_invalid": "لغة الواجهة إما الإنجليزية أو العربية.",
  "error.last_administrator": "هذا هو مسؤول النظام الوحيد. رقِّ شخصاً آخر إلى مسؤول نظام أولاً.",
  "error.memory_entry_not_found": "لا يوجد مثل هذا الإدخال في ذاكرة الإجابات.",
  "error.no_files": "لم يُرفع أي ملف.",
  "error.no_questions_found": "تعذّر استخراج أي أسئلة من الملف.",
  "error.no_questions_given": "لا توجد أسئلة لحفظها. اكتب سؤالاً واحداً على الأقل، أو أرفق ملف PDF أو Word.",
  "error.nothing_to_export": "لا توجد إجابات للتصدير.",
  "error.other_team": "لا يعمل على منتجات فريق آخر إلا مسؤول النظام.",
  "error.password_from_environment": "كلمة مرور هذا الحساب مأخوذة من إعدادات الخادم. أنشئ مسؤول نظام ثانياً بدلاً من ذلك.",
  "error.preview_failed": "تعذّرت معاينة الوثيقة.",
  "error.product_color_invalid": "اللون غير صالح. يُكتب رمزاً سداسياً عشرياً من ست خانات تسبقه العلامة #.",
  "error.product_description_too_long": "وصف المنتج أطول من المسموح.",
  "error.product_manager_required": "لا يغيّر منتجات الفريق إلا قادته ومسؤولو النظام.",
  "error.product_name_invalid": "اسم المنتج غير صالح.",
  "error.question_too_long": "السؤال أطول من المسموح.",
  "error.run_not_found": "لم يُعثر على عملية الإجابة هذه.",
  "error.run_not_in_progress": "لا توجد عملية إجابة جارية بهذا المعرّف.",
  "error.search_mode_unknown": "طريقة البحث غير معروفة.",
  "error.skill_not_found": "ليست لديك مهارة كهذه.",
  "error.source_not_found": "هذا المصدر ليس في قاعدة المعرفة.",
  "error.team_not_found": "لا يوجد فريق كهذا.",
  "error.too_many_questions": "عدد الأسئلة أكبر مما تتسع له قائمة واحدة.",
  "error.user_not_found": "لا يوجد مستخدم كهذا.",
  "error.route_not_found": "هذه الصفحة أو العملية غير موجودة.",
  "error.method_not_allowed": "هذه العملية غير مسموحة هنا.",
  "error.validation_failed": "بعض ما أُرسل غير صالح. راجِع الحقول ثم حاول مجدداً.",

  "This is the only administrator. Promote someone else first.": "هذا هو مسؤول النظام الوحيد. رقِّ شخصاً آخر إلى مسؤول نظام أولاً.",
  "This account's password comes from the environment and would be restored on the next restart. Create a second administrator instead.": "كلمة مرور هذا الحساب مأخوذة من إعدادات الخادم، وستُستعاد عند إعادة تشغيله التالية. أنشئ مسؤول نظام ثانياً بدلاً من ذلك.",
  "Sign in to continue.": "سجّل الدخول للمتابعة.",
  "Administrator access is required.": "يتطلب هذا صلاحية مسؤول النظام.",
  "Sign in as an administrator to view Phoenix.": "سجّل الدخول بحساب مسؤول نظام لعرض أداة التتبّع.",
  "Phoenix is not available.": "أداة التتبّع غير متاحة الآن. حاول لاحقاً.",
  "That conversation no longer exists.": "لم تعد هذه المحادثة موجودة.",
  "No model is configured for the assistant.": "لم يُضبط نموذج للمساعد.",
  "Fill the questionnaire first.": "املأ الاستبيان أولاً.",
  "No files were uploaded.": "لم يُرفع أي ملف.",
  "authority must be 'ours' or 'external'.": "يجب أن تكون الوثيقة إما وثيقتنا أو متطلباً خارجياً.",
  "No such entry in the answer memory.": "لا يوجد مثل هذا الإدخال في ذاكرة الإجابات.",
  "You have no skill like that.": "ليست لديك مهارة كهذه.",
  "Those preferences could not be applied.": "تعذّر تطبيق هذه التفضيلات.",
  "Only an administrator can work on another team's products.": "لا يعمل على منتجات فريق آخر إلا مسؤول النظام.",
  "Only the team's leads and administrators can change its products.": "لا يغيّر منتجات الفريق إلا قادته ومسؤولو النظام.",
  "No answer met the confidence threshold. Enable 'answers flagged for review' to export drafts.": "لم تبلغ أي إجابة حدّ الثقة. فعّل خيار تضمين الإجابات المعلَّمة للمراجعة لتصدير المسودات.",
  "Invalid document name.": "اسم الوثيقة غير صالح.",
  "Invalid document location.": "موقع الوثيقة غير صالح.",
  "Invalid document path.": "مسار الوثيقة غير صالح.",
  "That answer has not been reworded since it was drafted, so there is nothing to put back.": "لم تُعَد صياغة هذه الإجابة منذ كتابة مسودتها، فلا شيء لاستعادته.",
  "Say how the answers should change.": "قل كيف ينبغي أن تتغير الإجابات.",
  "You have no skill like that. Your skills are on the preferences page.": "ليست لديك مهارة كهذه. مهاراتك في صفحة التفضيلات.",
  "An answer is either the full one or the brief one.": "الإجابة إما كاملة أو مختصرة.",
  "A brief answer cannot be empty. To write nothing for this question, use Leave blank.": "لا يمكن أن تكون الإجابة المختصرة فارغة. لكي لا تكتب شيئاً لهذا السؤال، استخدم «اتركها فارغة».",
  "An answer is written full, brief, or however the file is set.": "تُكتب الإجابة كاملة أو مختصرة أو حسب إعداد الملف.",
  "Answer length must be one of full, brief.": "يجب أن تكون الإجابة إما كاملة أو مختصرة.",
  "There is no answer to approve for that question yet.": "لا توجد بعد إجابة لاعتمادها لهذا السؤال.",
  "That answer is deliberately blank. Write one before approving it.": "تُركت هذه الإجابة فارغة عن قصد. اكتب إجابة قبل اعتمادها.",
  "Answers cannot be written to a number column.": "لا يمكن كتابة الإجابات في عمود الأرقام.",
  "Answers cannot be written to a question column.": "لا يمكن كتابة الإجابات في عمود الأسئلة.",
  "Answers cannot be written to a theirs column.": "لا يمكن كتابة الإجابات في عمود خاص بالعميل.",
  "Answers cannot be written to a context column.": "لا يمكن كتابة الإجابات في عمود السياق.",
  "None of those questions are in this questionnaire.": "لا يوجد أي من هذه الأسئلة في هذا الاستبيان.",
  "A colour is written #RRGGBB, for example #2563eb.": "يُكتب اللون رمزاً سداسياً عشرياً من ست خانات تسبقه العلامة #.",
  "A chat's product is fixed once it starts. To work on another product, start a new chat with it chosen.": "منتج المحادثة ثابت منذ بدايتها. للعمل على منتج آخر، ابدأ محادثة جديدة واختره فيها.",
  "A questionnaire's product is fixed when it is opened. To answer this file for another product, close it and open the file again with that product chosen.": "منتج الاستبيان ثابت منذ فتحه. للإجابة عن هذا الملف لمنتج آخر، أغلقه ثم افتح الملف مجدداً بعد اختيار ذلك المنتج.",
  "{team} still has {n} member(s). Move or remove them first.": {
    "zero": "لا يزال في الفريق {team} أعضاء. انقلهم أو أزلهم أولاً.",
    "one": "لا يزال في الفريق {team} عضو واحد. انقله أو أزله أولاً.",
    "two": "لا يزال في الفريق {team} عضوان. انقلهما أو أزلهما أولاً.",
    "few": "لا يزال في الفريق {team} {n} أعضاء. انقلهم أو أزلهم أولاً.",
    "many": "لا يزال في الفريق {team} {n} عضواً. انقلهم أو أزلهم أولاً.",
    "other": "لا يزال في الفريق {team} {n} عضو. انقلهم أو أزلهم أولاً."
  },
  "Enter your email address.": "أدخل بريدك الإلكتروني.",
  "Enter your access code.": "أدخل رمز الدخول.",
  "That email and access code do not match.": "البريد الإلكتروني ورمز الدخول غير متطابقين.",
  "Too many attempts. Wait {n} minutes and try again.": {
    "zero": "محاولات كثيرة جداً. حاول مجدداً.",
    "one": "محاولات كثيرة جداً. انتظر دقيقة واحدة ثم حاول مجدداً.",
    "two": "محاولات كثيرة جداً. انتظر دقيقتين ثم حاول مجدداً.",
    "few": "محاولات كثيرة جداً. انتظر {n} دقائق ثم حاول مجدداً.",
    "many": "محاولات كثيرة جداً. انتظر {n} دقيقة ثم حاول مجدداً.",
    "other": "محاولات كثيرة جداً. انتظر {n} دقيقة ثم حاول مجدداً."
  },
  "The default length is either full or brief.": "تكون الإجابة افتراضياً إما كاملة أو مختصرة.",
  "The tone is as drafted, formal, or plain.": "النبرة إما كما في المسودة، أو رسمية، أو بسيطة.",
  "Policy references are either kept in the text or left to the citations.": "الإشارات إلى السياسات إما تبقى في النص أو تُترك للاستشهادات.",
  "Write what to call us without quotation marks.": "اكتب تسمية المنظمة دون علامات اقتباس.",
  "Built-in skills cannot be changed. Make a copy and edit that instead.": "لا يمكن تغيير المهارات المدمجة. أنشئ نسخة منها وعدّلها بدلاً من ذلك.",
  "A skill needs a name.": "تحتاج المهارة إلى اسم.",
  "A skill needs an instruction: how should the answers change?": "تحتاج المهارة إلى تعليمات: كيف ينبغي أن تتغير الإجابات؟",
  "The interface is in English or Arabic: en or ar.": "لغة الواجهة إما الإنجليزية أو العربية.",
  "There are no questions to keep. Type at least one, or give a PDF or Word file.": "لا توجد أسئلة لحفظها. اكتب سؤالاً واحداً على الأقل، أو أرفق ملف PDF أو Word.",
  "This questionnaire is a list of questions, with no file to write the answers into. Download the answers instead, as PDF, Word, CSV or JSON.": "هذا الاستبيان قائمة أسئلة بلا ملف تُكتب فيه الإجابات. نزّل الإجابات بدلاً من ذلك، بصيغة PDF أو Word أو CSV أو JSON.",
  "A chat is working with this questionnaire right now. Wait until it finishes.": "تعمل محادثة على هذا الاستبيان الآن. انتظر حتى تنتهي.",
  "This questionnaire is being answered right now. Wait until it finishes, then try again.": "يُجاب عن هذا الاستبيان الآن. انتظر حتى ينتهي ثم حاول مجدداً.",
  "This conversation is still working on your last message. Wait until it finishes, then try again.": "لا تزال هذه المحادثة تعمل على رسالتك الأخيرة. انتظر حتى تنتهي ثم حاول مجدداً.",
  "Previous answers are part of the answer memory. Manage them on the Answer memory page.": "الإجابات السابقة جزء من ذاكرة الإجابات. أدِرها من صفحة ذاكرة الإجابات.",
  "No Latin+Arabic TrueType font is installed, so a PDF cannot be rendered. Install DejaVu Sans (fonts-dejavu on Debian/Ubuntu).": "لا يوجد على الخادم خط يكتب الحروف اللاتينية والعربية معاً، لذا يتعذّر إنشاء ملف PDF. ثبّت خطاً كهذا على الخادم."
});

(function () {
  "use strict";

  /* The review's reasons, as `selection.ready_to_write` joins them ("; "), each
     in its own Arabic. A reason may hold "; " itself: PARTIAL_SOURCE does, and so
     may the drafter's words after INCONSISTENT. So a reason is the fewest pieces
     a sentence here knows, and takes the pieces after it that begin no reason
     while it is still known (the drafter's words). A piece no sentence knows
     stays as it came. */
  function reasons(joined) {
    const pieces = joined.split("; ");
    const known = (from, to) => {
      const sentence = pieces.slice(from, to + 1).join("; ");
      return I18n.server(sentence) !== sentence;
    };
    const begins = (from) => pieces.some((piece, to) => to >= from && known(from, to));
    const parts = [];
    let at = 0;
    while (at < pieces.length) {
      let end = at;
      while (end < pieces.length && !known(at, end)) end += 1;
      if (end === pieces.length) end = at;
      else while (end + 1 < pieces.length && !begins(end + 1) && known(at, end + 1)) end += 1;
      parts.push(pieces.slice(at, end + 1).join("; "));
      at = end + 1;
    }
    return parts.map((part) => I18n.server(part)).join("؛ ");
  }

  const counted = (english, name) => (whole, ...found) => {
    const params = { n: Number(found[name.indexOf("n")]) };
    name.forEach((key, index) => { if (key !== "n") params[key] = found[index]; });
    return I18n.t(english, params);
  };

  I18n.addPatterns([
    // The review's reasons (`verification.py`) that carry the case's own words.
    [/^cites clauses not covered by its sources: ([\s\S]+)$/, "تستشهد ببنود لا تغطيها مصادرها: $1"],
    [/^we are not consistent about this: ([\s\S]+)$/, "لسنا متسقين في هذا: $1"],

    // Why an answer is held back (`selection.ready_to_write`).
    [/^flagged for review -- ([\s\S]+)$/, (whole, joined) => I18n.t("flagged for review -- {reasons}", { reasons: reasons(joined) })],
    [/^confidence (\d+)%, at or under the (\d+)% threshold for writing without a person looking$/, "درجة الثقة $1%، وهي لا تتجاوز حدّ $2% اللازم لكتابتها في الملف دون أن يطّلع عليها شخص"],

    // Why the confidence is what it is (`verification.explain_confidence`), and a failed answer's.
    [/^A second model read the answer against the sources and could not trace every statement in it back to them\. The reviewer's note:\n ([\s\S]*)\. \nVerify each claim against the (\d+) cited sources? before submitting\.$/,
      counted("A second model read the answer against the sources and could not trace every statement in it back to them. The reviewer's note:\n {note}. \nVerify each claim against the {n} cited source(s) before submitting.", ["note", "n"])],
    [/^A second model read the answer against the sources and could not trace every statement in it back to them\. \nVerify each claim against the (\d+) cited sources? before submitting\.$/,
      counted("A second model read the answer against the sources and could not trace every statement in it back to them. \nVerify each claim against the {n} cited source(s) before submitting.", ["n"])],
    [/^No single clause states this outright, so the answer was inferred by combining related material from (\d+) sources?\. The reasoning is sound but worth a second pair of eyes\.$/,
      counted("No single clause states this outright, so the answer was inferred by combining related material from {n} source(s). The reasoning is sound but worth a second pair of eyes.", ["n"])],
    [/^Answering failed: ([\s\S]+)$/, "تعذّرت الإجابة: $1"],

    // The errors' messages the server fills in, where they are raised.
    [/^No user (.+)\.$/, "لا يوجد مستخدم بالعنوان $1."],
    [/^No team (['"]?)(.+)\1\.$/, "لا يوجد فريق «$2»."],
    [/^That file is not a (?:questionnaire|form) this can read\. Supported: .+\.$/, "لا يمكن قراءة هذا الملف كاستبيان. الصيغ المدعومة: Excel وWord."],
    [/^\.(\w+) is not a (?:questionnaire|form) this can read\. Supported: .+\.$/, "لا يمكن قراءة ملفات $1 كاستبيانات. الصيغ المدعومة: Excel وWord."],
    [/^'(.+)' is not supported\. Upload .+\.$/, "الملف «$1» غير مدعوم. ارفع ملف PDF أو Word."],
    [/^(['"])(.+)\1 is not in the knowledge base\.$/, "«$2» ليس في قاعدة المعرفة."],
    [/^No run '(.+)'\.$/, "لا توجد عملية إجابة بالمعرّف «$1»."],
    [/^unknown search mode '(.*)'$/, "طريقة البحث «$1» غير معروفة."],
    [/^No questions could be extracted from '(.+)'\.$/, "تعذّر استخراج أي أسئلة من «$1»."],
    [/^No run in progress with id '(.+)'\.$/, "لا توجد عملية إجابة جارية بالمعرّف «$1»."],
    [/^Document '(.+)' was not found\.$/, "لم يُعثر على الوثيقة «$1»."],
    [/^Could not preview '(.+)': it could not be read as a Word document\.$/, "تعذّرت معاينة «$1»: لم تمكن قراءته كوثيقة Word."],
    [/^Could not extract text from '(.+)'\.$/, "تعذّر استخراج النص من «$1»."],
    [/^No question (['"])(.+)\1 in this questionnaire\.$/, "لا يوجد سؤال «$2» في هذا الاستبيان."],
    [/^No answer for (['"])(.+)\1 yet\.$/, "لا توجد إجابة للسؤال «$2» بعد."],
    [/^The uploaded file for (['"])(.+)\1 is no longer on the server\. Upload it again to fill it in\.$/, "لم يعد الملف المرفوع «$2» موجوداً على الخادم. ارفعه مجدداً لملئه."],
    [/^No questions were found on (['"])(.+)\1\.$/, "لم يُعثر على أسئلة في الورقة «$2»."],
    [/^(['"])(.+)\1 is not a role\.$/, "«$2» ليس دوراً معروفاً لعمود."],
    [/^(.+) contains a part of ([\d,.]+) MB, past the (\d+) MB this reads\.$/, "يحتوي «$1» على جزء حجمه $2 ميغابايت، وهذا أكبر من $3 ميغابايت، وهو أقصى ما يُقرأ."],
    [/^(.+) is not a readable \.docx file\.$/, "«$1» ليس ملف Word يمكن قراءته."],
    [/^(.+) is not a readable \.xlsx file\.$/, "«$1» ليس ملف Excel يمكن قراءته."],
    [/^(.+) holds ([\d,]+) cells, past the ([\d,]+) this reads\. Split it into smaller files\.$/, "يحتوي «$1» على $2 من الخلايا، وهذا أكثر من $3، وهو أقصى ما يُقرأ. قسّمه إلى ملفات أصغر."],
    [/^(.+) lists no sheets, so there is nothing to read\.$/, "لا يحتوي «$1» على أي ورقة، فلا شيء يُقرأ."],
    [/^(.+) is missing a part it needs(?: \(.+\))?, so it is not a complete workbook\.$/, "ينقص «$1» جزءٌ يحتاجه، فهو ليس مصنَّف Excel كاملاً."],
    [/^(.+) contains XML that could not be read: ([\s\S]+)$/, "يحتوي «$1» على بيانات تعذّرت قراءتها: $2"],
    [/^No product (['"])(.+)\1 in this team\.$/, "لا يوجد منتج «$2» في هذا الفريق."],
    [/^(.+) was deleted, so this is kept read-only: it can still be read, and a questionnaire's filled file downloaded, but nothing in it can be changed\.$/, "حُذف المنتج $1، لذا يبقى هذا للقراءة فقط: يمكن قراءته وتنزيل الملف المملوء لاستبيانه، لكن لا يمكن تغيير أي شيء فيه."],
    [/^(.+) was deleted, and its knowledge base with it\.$/, "حُذف المنتج $1، وحُذفت معه قاعدة المعرفة الخاصة به."],
    [/^A product's name has 1 to (\d+) characters\.$/, "يتراوح عدد أحرف اسم المنتج بين 1 و$1."],
    [/^A description has at most (\d+) characters\.$/, "لا يتجاوز عدد أحرف الوصف $1."],
    [/^Type "(.+)" to delete a product\.$/, "اكتب «$1» لحذف المنتج."],
    [/^This team already has a product called (['"])(.+)\1\.$/, "لدى هذا الفريق منتج باسم «$2» بالفعل."],
    [/^(.+) still has (\d+) member\(s\)\. Move or remove them first\.$/, counted("{team} still has {n} member(s). Move or remove them first.", ["team", "n"])],
    [/^(['"])(.+)\1 is not an email address\.$/, "«$2» ليس عنوان بريد إلكتروني."],
    [/^Unknown role (['"])(.+)\1\.$/, "الدور «$2» غير معروف."],
    [/^Too many attempts\. Wait (\d+) minutes and try again\.$/, counted("Too many attempts. Wait {n} minutes and try again.", ["n"])],
    [/^Unknown preference: (.+)\.$/, "تفضيل غير معروف: $1."],
    [/^What to call us can be at most (\d+) characters\.$/, "لا يتجاوز عدد أحرف تسمية المنظمة $1."],
    [/^The extra line can be at most (\d+) characters; this one is (\d+)\.$/, "لا يتجاوز عدد أحرف السطر الإضافي $1، وعدد أحرف هذا السطر $2."],
    [/^You can keep at most (\d+) skills\. Remove one you no longer use first\.$/, "لا يمكنك الاحتفاظ بأكثر من $1 من المهارات. أزل أولاً مهارة لم تعد تستخدمها."],
    [/^A skill's name can be at most (\d+) characters\.$/, "لا يتجاوز عدد أحرف اسم المهارة $1."],
    [/^A skill's description can be at most (\d+) characters\.$/, "لا يتجاوز عدد أحرف وصف المهارة $1."],
    [/^A skill's instruction can be at most (\d+) characters\.$/, "لا يتجاوز عدد أحرف تعليمات المهارة $1."],
    [/^There is already a built-in skill called (['"])(.+)\1\. Make a copy to change it\.$/, "توجد مهارة مدمجة باسم «$2» بالفعل. أنشئ نسخة منها لتغييرها."],
    [/^You already have a skill called (['"])(.+)\1\.$/, "لديك مهارة باسم «$2» بالفعل."],
    [/^A list can hold at most (\d+) questions\.$/, "لا يتجاوز عدد أسئلة القائمة الواحدة $1."],
    [/^A question can be at most (\d+) characters\.$/, "لا يتجاوز عدد أحرف السؤال $1."],
    [/^No questionnaire (['"])(.+)\1\.$/, "لا يوجد استبيان «$2»."],
    [/^This questionnaire is being answered right now \((\d+) of (\d+) done\)\. Wait until it finishes, then try again\.$/, "يُجاب عن هذا الاستبيان الآن (أُنجز $1 من $2). انتظر حتى ينتهي ثم حاول مجدداً."],
    [/^Cannot read '(.+)'\. Supported types: .+$/, "تعذّرت قراءة «$1». الأنواع المدعومة: PDF وWord."],
    [/^No text found in '(.+)'\. Scanned images are not supported .+$/, "لم يُعثر على نص في «$1». الصور الممسوحة ضوئياً غير مدعومة ما لم يُفعَّل التعرّف الضوئي على الحروف في إعدادات الخادم."],
    [/^Could not convert '(.+)': ([\s\S]+)$/, "تعذّر تحويل «$1»: $2"],
  ]);
})();
