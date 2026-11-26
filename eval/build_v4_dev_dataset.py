"""
Deterministic builder for the SecureLink V4 synthetic development & challenge-test dataset
(`eval/datasets/v4_dev_300.json`, 300 scenarios).

All labels in this dataset are explicitly marked as SYNTHETIC AND PROVISIONAL
pending independent human/expert annotation and held-out evaluation.
Related paraphrases and contrasting context pairs share a `group:<id>` tag to prevent
cross-split leakage when partitioning development data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from eval.schema import EvalDataset


def _txt(
    sid: str,
    cat_tag: str,
    lang: str,
    ctx: str,
    utt: str,
    intent: str,
    level: str,
    sev: float,
    sev_range: Tuple[float, float],
    review: bool,
    group: str,
    teasing: bool = False,
    threat: bool = False,
    extra_tags: List[str] | None = None,
    notes: str = "",
) -> Dict[str, Any]:
    tags = ["synthetic_provisional", f"category:{cat_tag}", f"group:{group}"]
    if extra_tags:
        tags.extend(extra_tags)
    return {
        "id": sid,
        "split": "dev",
        "mode": "text",
        "language": lang,
        "conversational_context": ctx,
        "utterance": utt,
        "expected_intent": intent,
        "expected_level": level,
        "provisional_severity": sev,
        "provisional_severity_range": list(sev_range),
        "expected_review_required": review,
        "is_friendly_teasing": teasing,
        "is_serious_threat": threat,
        "tags": tags,
        "notes": notes or "Synthetic provisional label; requires human rubric review before final thesis reporting.",
    }


def _mt(
    sid: str,
    lang: str,
    ctx: str,
    turns: List[Tuple[str, float, str]],
    intent: str,
    level: str,
    sev: float,
    sev_range: Tuple[float, float],
    review: bool,
    group: str,
    teasing: bool = False,
    threat: bool = False,
    extra_tags: List[str] | None = None,
    notes: str = "",
) -> Dict[str, Any]:
    tags = ["synthetic_provisional", "category:multi_turn_conversation", f"group:{group}"]
    if extra_tags:
        tags.extend(extra_tags)
    return {
        "id": sid,
        "split": "dev",
        "mode": "multi_turn",
        "language": lang,
        "conversational_context": ctx,
        "turns": [
            {"utterance": u, "timestamp_offset_sec": ts, "speaker_role": role}
            for u, ts, role in turns
        ],
        "expected_intent": intent,
        "expected_level": level,
        "provisional_severity": sev,
        "provisional_severity_range": list(sev_range),
        "expected_review_required": review,
        "is_friendly_teasing": teasing,
        "is_serious_threat": threat,
        "tags": tags,
        "notes": notes or "Synthetic provisional multi-turn label; requires human rubric review.",
    }


def build_scenarios() -> List[Dict[str, Any]]:
    scenarios: List[Dict[str, Any]] = []

    # =========================================================================
    # 1. ORDINARY CONVERSATION (45)
    # =========================================================================
    ordinary_items = [
        ("tl", "Morning greeting in hallway.", "Magandang umaga po ma'am, tulungan ko na po kayo sa gamit.", "grp_greet"),
        ("taglish", "Asking classmate for notes.", "Pahiram naman ng notes sa GenMath, di ko nakopya kanina.", "grp_notes"),
        ("en", "Discussing group presentation slides.", "Can you share the Canva link for our science slides before lunch?", "grp_slides"),
        ("tl", "Inviting friend to canteen.", "Tara sa canteen, nagugutom na ako eh.", "grp_canteen"),
        ("taglish", "Talking about school commute.", "Grabe yung traffic sa EDSA kanina, muntik na akong ma-late.", "grp_commute"),
        ("tl", "Asking about class schedule.", "Anong oras nga ulit yung PE natin ngayong hapon?", "grp_sched"),
        ("en", "Borrowing a pen in class.", "Do you have an extra black ballpen I can borrow for the quiz?", "grp_pen"),
        ("taglish", "Coordinating research defense.", "Practice tayo ng script natin sa research defense sa library mamaya.", "grp_defense"),
        ("tl", "Talking about weather.", "Ang lakas ng ulan sa labas, may dala ka bang payong?", "grp_rain"),
        ("taglish", "Checking assignment deadline.", "Uy, bukas na ba deadline nung reflection paper sa Philosophy?", "grp_deadline"),
        ("en", "Complimenting a drawing.", "Your poster design for nutrition month looks really clean.", "grp_poster"),
        ("tl", "Asking for directions on campus.", "Excuse me, saan po banda yung Registrar's Office dito?", "grp_dir"),
        ("taglish", "Discussing school club.", "Sasali ka ba sa robotics club o sa journalism this semester?", "grp_club"),
        ("tl", "Sharing snacks.", "Kuha ka ng biscuits dito, marami akong dala ngayon.", "grp_snack"),
        ("en", "Checking attendance.", "Did sir already call my name for attendance?", "grp_attend"),
        ("taglish", "Talking about basketball intramurals.", "Ang galing ng three-pointer nung Section B sa intrams kanina.", "grp_intrams"),
        ("tl", "Asking about library hours.", "Hanggang alas-singko ba bukas yung library ngayong Biyernes?", "grp_lib"),
        ("taglish", "Planning study group.", "Mag-review tayo sa bahay nina Carlo para sa quarterly exam.", "grp_study"),
        ("en", "Discussing lab equipment.", "Please handle the microscope carefully and wipe the lens after use.", "grp_lab"),
        ("tl", "Reminding friend about ID.", "Suotin mo na yung school ID mo, mahigpit yung guard sa gate.", "grp_id"),
        ("taglish", "Asking about Wi-Fi password in computer lab.", "Gumagana ba yung internet sa PC number twelve?", "grp_pc"),
        ("tl", "Talking about family dinner.", "Susunduin daw ako ni kuya pagkatapos ng klase kasi birthday ni lola.", "grp_fam"),
        ("en", "Asking teacher a question.", "Ma'am, could you explain step three of the titration procedure again?", "grp_q"),
        ("taglish", "Talking about phone battery.", "Lowbat na phone ko, may powerbank ka ba diyan?", "grp_batt"),
        ("tl", "Discussing classroom cleaning.", "Sino cleaners ngayong Miyerkules? Tayo na magwalis ng sahig.", "grp_clean"),
        ("taglish", "ASR typo: 'paaralan' and 'tara' (tests prompt-echo false rejection).", "Tara na sa paaralan, baka magsimula na yung flag ceremony.", "grp_echo1"),
        ("tl", "Polite school greeting (tests prompt-echo false rejection).", "Magandang araw po, kumusta na po kayo?", "grp_echo2"),
        ("taglish", "Casual pause request (tests prompt-echo).", "Sandali lang po, opo, kukunin ko lang yung notebook ko.", "grp_echo3"),
        ("en", "Talking about music playlist.", "I've been listening to that new OPM indie album all morning.", "grp_music"),
        ("tl", "Asking about water refill.", "Saan yung water fountain dito sa third floor?", "grp_water"),
        ("taglish", "Discussing coding homework.", "Nag-error yung Python script ko sa loop, patulong naman mag-debug.", "grp_code"),
        ("tl", "Confirming class dismissal.", "Wala na raw klase sa last period kasi may faculty meeting.", "grp_dismiss"),
        ("en", "Talking about lunch order.", "I ordered chicken adobo and rice from the cafeteria counter.", "grp_lunch"),
        ("taglish", "Talking about school uniform.", "Nakalimutan ko yung PE shirt ko sa locker kahapon.", "grp_uniform"),
        ("tl", "Friendly goodbye at dismissal.", "Ingat ka pauwi ha, chat mo ko pag nakarating ka na.", "grp_bye"),
        ("taglish", "Discussing pet dog.", "Ang kulit ng aso namin kagabi, kinain niya yung tsinelas ko.", "grp_pet"),
        ("en", "Organizing charity drive.", "Let's sort the donated books by grade level before packing them.", "grp_drive"),
        ("tl", "Asking about photocopy shop.", "Bukas pa kaya yung xerox sa tapat ng gate?", "grp_xerox"),
        ("taglish", "ASR mild spelling error in benign chat.", "Paki send naman yung pdf files sa group chat natin later.", "grp_pdf"),
        ("tl", "Talking about favorite subject.", "Mas gusto ko yung Biology kaysa Physics kasi mas nakaka-enjoy.", "grp_subj"),
        ("en", "Checking watch for bus.", "The school shuttle leaves in ten minutes, we should head downstairs.", "grp_bus"),
        ("taglish", "Talking about allowance budgeting (benign, contains 'baon').", "Nag-iipon ako ng baon ko ngayong linggo para pambili ng gitara.", "grp_baon_benign"),
        ("tl", "Talking about paying class fund (benign, contains 'bayad').", "Nagbayad na ako ng twenty pesos para sa class photocopy fund.", "grp_bayad_benign"),
        ("taglish", "Untargeted frustration at broken pen.", "Bwisit naman tong ballpen na to, ayaw sumulat habang nag-eexam.", "grp_vent1"),
        ("en", "Untargeted frustration at spilled drink.", "Oh crap, I spilled iced tea all over my scratch paper.", "grp_vent2"),
    ]
    for i, (lang, ctx, utt, grp) in enumerate(ordinary_items, 1):
        extra = ["asr_error"] if "ASR" in ctx else (["untargeted_profanity"] if "frustration" in ctx else [])
        scenarios.append(_txt(
            f"V4-DEV-ORD-{i:03d}", "ordinary_conversation", lang, ctx, utt,
            "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, grp, extra_tags=extra
        ))

    # =========================================================================
    # 2. FRIENDLY TEASING AND MUTUAL BANTER (40)
    # =========================================================================
    teasing_items = [
        ("tl", "Close friends laughing together; affectionate gay-friend banter with mutual laughter.", "Hoy, bakla ka! Ang tagal mo mag-ayos, tara na haha!", "grp_bakla", ["identity_term", "bakla_benign"]),
        ("taglish", "Friendly banter with 'bakla' among close barkada laughing.", "Bakla ka talaga bes, ang ganda ng hair mo today char!", "grp_bakla", ["identity_term", "bakla_benign"]),
        ("taglish", "Playful Mobile Legends gaming banter between friends.", "Ang bobo mo naman mag-tank sa ML pre, haha bawi next game!", "grp_gaming", ["gaming_banter"]),
        ("taglish", "Playful Valorant banter with mutual laughter.", "Tanga mo pre sablay yung ulti mo haha, clutch ko na to!", "grp_gaming", ["gaming_banter"]),
        ("taglish", "Playful Tekken challenge between friends.", "Bugbugin kita sa Tekken mamaya sa bahay, rematch tayo!", "grp_gaming", ["gaming_banter"]),
        ("tl", "Playful basketball trash talk among teammates.", "Wala kang tira ngayon pre haha, libre mo kaming fishball!", "grp_sports", ["sports_banter"]),
        ("taglish", "Friendly teasing about being late.", "Hoy siraulo, late ka na naman sa first period haha!", "grp_late", ["friend_banter"]),
        ("tl", "Friendly teasing about crush.", "Ayiee, patay na patay ka na naman kay Ana, namumula ka oh!", "grp_crush", ["friend_banter"]),
        ("taglish", "Friendly teasing with mild slang compliment.", "Uy gago ang lupit ng bagong sapatos mo ah, sana all!", "grp_compliment", ["profanity_benign"]),
        ("taglish", "Friendly banter about math mistakes while laughing.", "Bobo mo sa algebra pre haha, halika paturo ka na nga sakin.", "grp_math_banter", ["friend_banter"]),
        ("en", "Playful friend teasing about forgetting umbrella.", "You're such a dork, you forgot your umbrella again lol.", "grp_en_banter", ["friend_banter"]),
        ("taglish", "Joking about eating friend's fries.", "Loko loko ka talaga, inubos mo yung fries ko habang nagsasalita ako haha!", "grp_food_banter", ["friend_banter"]),
        ("tl", "Playful friend greeting.", "Hoy mokong, saan ka galing kanina? Hinahanap ka ng tropa!", "grp_mokong", ["friend_banter"]),
        ("taglish", "Playful teasing about singing.", "Grabe boses mo bes, uulan na yata haha joke lang ang galing!", "grp_sing", ["friend_banter"]),
        ("en", "Friendly gaming rivalry.", "I'm totally going to destroy your high score in chess club today!", "grp_chess", ["gaming_banter"]),
        ("taglish", "Friendly banter about hair.", "Parang bagong gising ka pa pre haha, suklay-suklay din!", "grp_hair", ["friend_banter"]),
        ("tl", "Mutual joking about quiz score.", "Pareho tayong bagsak sa quiz pre, apir tayo mga sabaw haha!", "grp_sabaw", ["friend_banter"]),
        ("taglish", "Joking about lending money back.", "Hoy bayaran mo na yung bente kong utang mo kahapon haha, libre mo ko kwek-kwek!", "grp_utang", ["friend_banter"]),
        ("tl", "Playful teasing about height among close friends laughing.", "Ang liit mo talaga bes haha, abot mo ba yung locker sa taas?", "grp_height", ["friend_banter"]),
        ("taglish", "Friendly banter with 'gago' as exclamation of surprise.", "Gago ka pre, ang taas ng score mo sa physics, ikaw na lodi!", "grp_compliment", ["profanity_benign"]),
        ("taglish", "Playful anime/game reference.", "Patayin kita sa 1v1 mamaya sa comp shop, pustahan siomai!", "grp_gaming", ["gaming_banter"]),
        ("en", "Friendly teasing among teammates.", "No way you missed that layup bro, haha you owe us water!", "grp_sports", ["sports_banter"]),
        ("taglish", "Joking about sleepy classmate.", "Hoy tulog mantika, gising na recess na uy haha!", "grp_sleep", ["friend_banter"]),
        ("tl", "Friendly banter with 'charot'.", "Ang pangit ng sulat ko ngayon, mas maganda pa sulat ng doktor charot!", "grp_self", ["self_teasing"]),
        ("taglish", "Playful teasing about slow walker.", "Bilisan mo maglakad bes, forda pagong ka today haha!", "grp_walk", ["slang"]),
        ("tl", "Friendly teasing about picky eating.", "Ang arte mo kumain pre haha, gulay lang yan eh!", "grp_eat", ["friend_banter"]),
        ("taglish", "Friendly joke about forgetting lines in skit.", "Sabaw ka na naman sa rehearsal bes haha, okay lang bawi tayo!", "grp_rehearse", ["friend_banter"]),
        ("en", "Playful banter about terrible pun.", "That joke was so bad I'm banning you from the study table haha.", "grp_pun", ["friend_banter"]),
        ("taglish", "Joking with friend about sharing snacks.", "Akin na lang tong sobrang chips mo kung busog ka na haha.", "grp_snack_joke", ["friend_banter"]),
        ("tl", "Affectionate teasing among best friends.", "Baliw ka talaga, pinatawa mo na naman ako habang nagtuturo si sir!", "grp_laugh", ["friend_banter"]),
        ("taglish", "ASR error on friendly gaming banter ('ml' -> 'em el').", "Ang bobo mo sa em el pre haha, carry na lang kita!", "grp_gaming", ["gaming_banter", "asr_error"]),
        ("tl", "Playful teasing about selfie.", "Grabe yung filter mo beh, di kita nakilala haha ang ganda!", "grp_selfie", ["slang"]),
        ("taglish", "Joking about messy desk.", "Parang binagyo yung desk mo pre haha, tulungan na kita mag-ayos.", "grp_desk", ["friend_banter"]),
        ("en", "Friendly banter about coffee addiction.", "You're basically ninety percent iced coffee at this point lol.", "grp_coffee", ["friend_banter"]),
        ("taglish", "Friendly banter with 'amaccana'.", "Amaccana accla, kanina ka pa nagkukuwento tungkol sa crush mo haha!", "grp_bakla", ["slang", "identity_term"]),
        ("tl", "Joking about losing at rock-paper-scissors.", "Talo ka sa bato-bato-pik, ikaw bibili ng tubig namin haha!", "grp_rps", ["friend_banter"]),
        ("taglish", "Playful teasing about outfit.", "Forda formal ka today pre, may interview ka ba haha?", "grp_outfit", ["slang"]),
        ("en", "Playful teasing between siblings/friends.", "Stop hogging the electric fan you goofball, share some air!", "grp_fan", ["friend_banter"]),
        ("taglish", "Friendly banter about exam panic.", "Siraulo ka talaga, sabi mo di ka nag-aral tapos perfect ka sa quiz haha!", "grp_quiz_banter", ["friend_banter"]),
        ("tl", "Warm teasing about friend's laugh.", "Ang lakas ng tawa mo bes, rinig hanggang kabilang room haha!", "grp_laugh", ["friend_banter"]),
    ]
    for i, (lang, ctx, utt, grp, etags) in enumerate(teasing_items, 1):
        scenarios.append(_txt(
            f"V4-DEV-TEASE-{i:03d}", "friendly_teasing", lang, ctx, utt,
            "ORDINARY_CONVERSATION", "NORMAL", 1.2, (0.0, 2.5), False, grp,
            teasing=True, extra_tags=etags
        ))

    # =========================================================================
    # 3. VERBAL HARASSMENT (40)
    # =========================================================================
    harass_items = [
        ("tl", "Hostile homophobic slur directed at student to humiliate them.", "Hoy, bakla ka! Lumayo ka nga dito, nakakadiri ka!", "grp_bakla", ["identity_term", "bakla_harmful"]),
        ("taglish", "Mocking student's sexuality and excluding them from group.", "Wag niyo isali yan, bakla yan eh, nakakahiya kasama sa group!", "grp_bakla", ["identity_term", "exclusion"]),
        ("tl", "Direct repeated insult attacking intelligence.", "Ang bobo mo talaga, simpleng problem hindi mo maintindihan, inutil!", "grp_insult1", ["targeted_insult"]),
        ("tl", "Body shaming and humiliation in hallway.", "Ang pangit mo, mukha kang basurahan, umalis ka nga dito!", "grp_body1", ["body_shaming"]),
        ("tl", "Demeaning worthlessness attack.", "Wala kang kwenta dito sa classroom, pabigat ka lang sa lahat!", "grp_worth1", ["targeted_insult"]),
        ("taglish", "Social exclusion and cruel mockery.", "Nobody wants you in our group, ang weird mo at ang baho mo pa!", "grp_excl1", ["exclusion", "body_shaming"]),
        ("en", "Direct English verbal abuse.", "You're so stupid and worthless, why do you even come to school?", "grp_en_har1", ["targeted_insult"]),
        ("tl", "Targeted profanity and insult.", "Putangina mo, ang tanga tanga mo kahit kailan!", "grp_prof1", ["targeted_profanity"]),
        ("tl", "Cruel hygiene mockery.", "Ang asim mo tignan, wag ka nga tumabi sa amin!", "grp_hyg1", ["body_shaming"]),
        ("taglish", "Mocking appearance with slang.", "Kadiri ka tignan, mukha kang ewan, lumayas ka sa upuan namin!", "grp_body2", ["body_shaming"]),
        ("tl", "Calling classmate a burden and freeloader.", "Palamunin ka na nga sa bahay, pabigat ka pa dito sa project!", "grp_burden1", ["targeted_insult"]),
        ("en", "Telling classmate to shut up with insult.", "Shut up, idiot, nobody asked for your stupid opinion!", "grp_en_har2", ["targeted_insult"]),
        ("taglish", "Derogatory disability slur.", "Monggoloid ka ba? Bakit ganyan ka magsalita, nakakatawa ka!", "grp_ableist1", ["slur"]),
        ("tl", "Calling classmate crazy/abnormal to humiliate.", "Abnoy ka talaga, walang gustong makipagkaibigan sa'yo!", "grp_ableist2", ["slur", "exclusion"]),
        ("taglish", "Mocking student's accent and background.", "Ang probinsyano ng accent mo, ang baduy mo mag-English, loser!", "grp_accent1", ["discrimination"]),
        ("tl", "Targeted insult with ASR typo ('ang bobo' -> 'ambobo').", "Ambobo mo talaga, umuwi ka na lang sa inyo!", "grp_insult2", ["asr_error"]),
        ("taglish", "Cruel weight shaming.", "Ang taba taba mo na nga, kain ka pa nang kain, parang baboy!", "grp_body3", ["body_shaming"]),
        ("en", "Humiliating student in front of peers.", "Look at this freak, you don't belong here, get out!", "grp_en_har3", ["exclusion"]),
        ("tl", "Aggressive verbal degradation.", "Salot ka sa section natin, sana lumipat ka na ng school!", "grp_worth2", ["targeted_insult"]),
        ("taglish", "Mocking student's clothes/poverty.", "Ang luma ng sapatos mo, wala ba kayong pambili? Kawawa ka naman!", "grp_class1", ["socioeconomic_mockery"]),
        ("tl", "Direct personal curse.", "Gago ka, tangina mo, ang kapal ng mukha mo lumapit dito!", "grp_prof2", ["targeted_profanity"]),
        ("taglish", "Repeatedly belittling academic effort.", "Wala kang silbi, kahit anong gawin mo bobo ka pa rin!", "grp_insult3", ["targeted_insult"]),
        ("en", "Targeted verbal bullying about appearance.", "You are so ugly, stop looking at us you loser!", "grp_en_har4", ["body_shaming"]),
        ("tl", "Calling classmate stupid and useless.", "Inutil ka ba? Hindi mo gets yung pinakasimpleng utos?", "grp_insult4", ["targeted_insult"]),
        ("taglish", "Social ostracism.", "Walang may gusto sa'yo dito, alis ka na sa table namin!", "grp_excl2", ["exclusion"]),
        ("tl", "Insulting intelligence with harsh tone.", "Sobrang tanga mo talaga, nakakahiya ka maging kaklase!", "grp_insult5", ["targeted_insult"]),
        ("taglish", "Mocking acne/skin.", "Ang dami mong pimples, kadiri tignan mukha mo!", "grp_body4", ["body_shaming"]),
        ("en", "Verbal harassment dismissing student.", "You're a complete joke, everyone laughs at you behind your back.", "grp_en_har5", ["social_humiliation"]),
        ("tl", "Harsh dismissal and name-calling.", "Tumahimik ka nga, tarantado ka, wala kang karapatan magsalita!", "grp_prof3", ["targeted_profanity"]),
        ("taglish", "Cruel teasing ignoring victim's presence.", "Bakit ka pa nandito? You're literally the biggest loser in Grade 9!", "grp_en_har6", ["social_humiliation"]),
        ("tl", "Mocking student's family background.", "Pareho lang kayong walang kwenta ng pamilya mo!", "grp_fam_insult", ["targeted_insult"]),
        ("taglish", "ASR-noisy targeted insult ('walang kwenta' -> 'wala kang kuwenta').", "Wala kang kuwenta kausap, ang pangit mo pa!", "grp_worth3", ["asr_error"]),
        ("tl", "Aggressive verbal mockery.", "Siraulo ka ba? Ang bobo ng sagot mo kanina, pinagtawanan ka ng lahat!", "grp_insult6", ["social_humiliation"]),
        ("en", "Telling student nobody likes them.", "Nobody likes you here, go sit by yourself like a freak.", "grp_en_har7", ["exclusion"]),
        ("taglish", "Mocking physical trait.", "Ang laki ng ilong mo, kaya walang nagkakagusto sa'yo eh!", "grp_body5", ["body_shaming"]),
        ("tl", "Cruel exclusion from classroom activity.", "Mga pangit lang sumasali sa'yo, wag kang didikit sa grupo namin!", "grp_excl3", ["exclusion"]),
        ("taglish", "Targeted profanity with humiliation.", "Tangina mo ang bobo mo, ikaw dahilan kung bakit mababa grade namin!", "grp_prof4", ["targeted_profanity"]),
        ("en", "Demeaning name-calling.", "You're pathetic, stop crying like a baby!", "grp_en_har8", ["targeted_insult"]),
        ("tl", "Insulting speech/stutter.", "Bakit ka nauutal? Ang tanga mo magbasa sa harap ng klase!", "grp_speech_mock", ["social_humiliation"]),
        ("taglish", "Mixed benign opener followed by cruel verbal harassment.", "Uy congrats pala sa attendance mo, pero ang bobo at walang kwenta mo pa rin sa klase!", "grp_mixed_har", ["mixed_clause"]),
    ]
    for i, (lang, ctx, utt, grp, etags) in enumerate(harass_items, 1):
        scenarios.append(_txt(
            f"V4-DEV-HAR-{i:03d}", "verbal_harassment", lang, ctx, utt,
            "VERBAL_HARASSMENT", "THREAT", 6.0, (4.5, 7.8), False, grp, extra_tags=etags
        ))

    # =========================================================================
    # 4. AMBIGUOUS EXPRESSIONS (35) — MUST FLAG HUMAN REVIEW, NOT AUTO-BULLYING
    # =========================================================================
    ambig_items = [
        ("tl", "Isolated Filipino identity expression; no tone, relationship, or surrounding context.", "Hoy, bakla ka!", "grp_bakla", ["identity_term", "bakla_ambiguous", "insufficient_context"]),
        ("tl", "Isolated 'bakla' callout across hallway; could be friend or bully.", "Uy bakla, halika nga dito.", "grp_bakla", ["identity_term", "insufficient_context"]),
        ("taglish", "Isolated 'tomboy' remark without clear hostile or friendly cues.", "Tomboy ka ba talaga?", "grp_identity2", ["identity_term", "insufficient_context"]),
        ("tl", "Single-word insult fragment without target or context.", "Ang bobo naman.", "grp_frag1", ["insufficient_context"]),
        ("taglish", "Ambiguous 'gago ka' with no laughter or follow-up.", "Gago ka talaga.", "grp_prof_ambig", ["profanity_ambiguous", "insufficient_context"]),
        ("tl", "Ambiguous 'lagot ka' — could be about homework or a threat.", "Lagot ka mamaya.", "grp_lagot_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous 'tignan natin' — could be competition or intimidation.", "Tignan natin mamaya pagkatapos ng klase.", "grp_tignan", ["insufficient_context"]),
        ("en", "Ambiguous 'watch yourself' without context.", "You better watch yourself.", "grp_watch", ["insufficient_context"]),
        ("tl", "Isolated 'pangit mo' — could be sibling teasing or bullying.", "Ang pangit mo.", "grp_pangit_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous money request — could be debt repayment or extortion.", "Bigyan mo na ako ng fifty pesos ngayon.", "grp_money_ambig", ["insufficient_context"]),
        ("tl", "Ambiguous request to talk outside — could be private chat or confrontation.", "Mag-usap tayo sa labas mamaya.", "grp_usap_ambig", ["insufficient_context"]),
        ("en", "Ambiguous 'we're not done' — could be group project or threat.", "We are not done yet, see you after class.", "grp_done_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous teasing about weight without laughter marker.", "Ang taba mo na uy.", "grp_body_ambig", ["insufficient_context"]),
        ("tl", "Ambiguous 'tanga ka' without surrounding context.", "Tanga ka pala eh.", "grp_tanga_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous 'umalis ka dito' — could be seat saving or exclusion.", "Umalis ka nga dito.", "grp_alis_ambig", ["insufficient_context"]),
        ("en", "Ambiguous 'shut up' — could be playful disbelief or hostility.", "Oh shut up, you don't know anything.", "grp_shutup_ambig", ["insufficient_context"]),
        ("tl", "Ambiguous 'yari ka' — could be teacher scolding or peer threat.", "Yari ka kay sir mamaya.", "grp_yari_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous 'ibigay mo na' — could be borrowing phone or taking property.", "Ibigay mo na sakin yan.", "grp_give_ambig", ["insufficient_context"]),
        ("tl", "Fragmented ASR transcript with possible threat word.", "sa gate... mamaya... ikaw...", "grp_asr_frag1", ["asr_error", "insufficient_context"]),
        ("taglish", "Ambiguous discomfort phrase without clear perpetrator utterance.", "Tama na, wag na nga.", "grp_stop_ambig", ["discomfort", "insufficient_context"]),
        ("en", "Ambiguous 'stop it' — could be tickling, joking, or harassment.", "Hey, stop it already.", "grp_stop_en", ["discomfort", "insufficient_context"]),
        ("tl", "Ambiguous 'huwag ka maingay' — could be library shushing or silencing.", "Huwag kang maingay, wag ka magsabi kahit kanino.", "grp_quiet_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous regional term without clear derogatory intent.", "Bisaya ka pala, halata sa punto mo.", "grp_region_ambig", ["identity_term", "insufficient_context"]),
        ("tl", "Ambiguous 'siraulo ka' — very common among friends and enemies alike.", "Siraulo ka talaga eh.", "grp_sira_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous 'weird mo' — could be playful or alienating.", "Ang weird mo talaga minsan.", "grp_weird_ambig", ["insufficient_context"]),
        ("en", "Ambiguous 'you're dead' — could be about failing a test or physical threat.", "You're dead when she finds out.", "grp_dead_ambig", ["insufficient_context"]),
        ("tl", "Ambiguous 'baho mo' — could be post-PE joking or bullying.", "Hoy ang baho mo na.", "grp_baho_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous 'patay ka' — common Tagalog idiom for 'you're in trouble'.", "Patay ka na naman sa nanay mo.", "grp_patay_ambig", ["insufficient_context"]),
        ("tl", "Ambiguous ASR misspelling of 'bakla ka'.", "Hoy bak la ka.", "grp_bakla", ["identity_term", "asr_error", "insufficient_context"]),
        ("taglish", "Ambiguous 'wag ka lumapit' — could be prank or exclusion.", "Wag ka ngang lumapit sakin.", "grp_lapit_ambig", ["insufficient_context"]),
        ("en", "Ambiguous 'nobody asked you'.", "Literally nobody asked you.", "grp_ask_ambig", ["insufficient_context"]),
        ("tl", "Ambiguous 'hindi na nakakatuwa' — signals discomfort, needs prior context.", "Hindi na nakakatuwa yan ah.", "grp_discomfort1", ["discomfort", "insufficient_context"]),
        ("taglish", "Ambiguous 'akin na yan' — could be reclaiming own pen or taking item.", "Akin na nga yan, bilis!", "grp_take_ambig", ["insufficient_context"]),
        ("tl", "Ambiguous 'abangan mo' — could be movie/exam result or intimidation.", "Abangan mo na lang mamaya.", "grp_abang_ambig", ["insufficient_context"]),
        ("taglish", "Ambiguous 'loser' in unclear setting.", "Ang loser mo naman.", "grp_loser_ambig", ["insufficient_context"]),
    ]
    for i, (lang, ctx, utt, grp, etags) in enumerate(ambig_items, 1):
        is_tease = "bakla_ambiguous" in etags
        scenarios.append(_txt(
            f"V4-DEV-AMB-{i:03d}", "ambiguous_expression", lang, ctx, utt,
            "AMBIGUOUS_CONTEXT", "WARNING", 3.0, (2.0, 3.9), True, grp,
            teasing=is_tease, extra_tags=etags
        ))

    # =========================================================================
    # 5. DIRECT AND INDIRECT THREATS (35)
    # =========================================================================
    threat_items = [
        ("tl", "Explicit lethal threat at campus gate.", "Papatayin kita mamaya sa gate!", "DIRECT_THREAT", "DANGER", 9.5, (8.0, 10.0), False, "grp_phys1", ["lethal"]),
        ("tl", "Explicit weapon threat (stabbing).", "Sasaksakin kita paglabas mo ng classroom!", "DIRECT_THREAT", "DANGER", 9.5, (8.0, 10.0), False, "grp_phys2", ["weapon"]),
        ("tl", "Direct assault threat (punching).", "Sasapakin kita ngayon na!", "DIRECT_THREAT", "DANGER", 9.0, (8.0, 10.0), False, "grp_phys3", ["battery"]),
        ("tl", "Direct battery threat after school.", "Bubugbugin kita mamayang uwian sa labas!", "DIRECT_THREAT", "DANGER", 9.0, (8.0, 10.0), False, "grp_phys4", ["battery"]),
        ("en", "Explicit English lethal threat.", "I will kill you if you come near me again!", "DIRECT_THREAT", "DANGER", 9.2, (8.0, 10.0), False, "grp_phys5", ["lethal"]),
        ("en", "Explicit English assault threat.", "I'll beat you up right now after class!", "DIRECT_THREAT", "DANGER", 8.8, (8.0, 10.0), False, "grp_phys6", ["battery"]),
        ("tl", "Direct kicking threat.", "Tatadyakan kita pababa ng hagdan!", "DIRECT_THREAT", "DANGER", 8.5, (8.0, 10.0), False, "grp_phys7", ["battery"]),
        ("tl", "Direct beating threat ('uupakan').", "Uupakan kita sa banyo mamaya!", "DIRECT_THREAT", "DANGER", 8.8, (8.0, 10.0), False, "grp_phys8", ["battery"]),
        ("tl", "Lethal gang threat ('itutumba').", "Itutumba kita, wag kang magpakita sakin!", "DIRECT_THREAT", "DANGER", 9.2, (8.0, 10.0), False, "grp_phys9", ["lethal"]),
        ("tl", "Weapon threat ('babarilin').", "Babarilin kita pag nakita kita sa labas!", "DIRECT_THREAT", "DANGER", 9.5, (8.0, 10.0), False, "grp_phys10", ["weapon"]),
        # Serious threats masked with "joke lang" / "biro lang" / "charot lang"
        ("taglish", "Lethal threat followed by 'joke lang' — MUST NOT be suppressed to NORMAL.", "Papatayin kita mamaya sa gate, joke lang.", "DIRECT_THREAT", "THREAT", 7.5, (5.5, 9.0), True, "grp_joke_threat1", ["humor_masked_threat", "adversarial"]),
        ("taglish", "Assault threat followed by 'biro lang' — MUST NOT be suppressed.", "Bubugbugin kita paglabas mo ng school, biro lang!", "DIRECT_THREAT", "THREAT", 7.2, (5.5, 8.8), True, "grp_joke_threat2", ["humor_masked_threat", "adversarial"]),
        ("taglish", "Punching threat followed by 'charot lang' — MUST NOT be suppressed.", "Sasapakin kita sa mukha ngayon, charot lang.", "DIRECT_THREAT", "THREAT", 7.0, (5.0, 8.5), True, "grp_joke_threat3", ["humor_masked_threat", "adversarial"]),
        ("en", "English lethal threat followed by 'just kidding'.", "I will stab you after school, just kidding.", "DIRECT_THREAT", "THREAT", 7.5, (5.5, 9.0), True, "grp_joke_threat4", ["humor_masked_threat", "adversarial"]),
        # Mixed benign + harmful clauses
        ("taglish", "Benign greeting followed by direct assault threat.", "Kumusta ka na pre? Pero mamaya susuntukin kita sa labas!", "DIRECT_THREAT", "DANGER", 8.8, (7.5, 10.0), False, "grp_mixed_thr1", ["mixed_clause"]),
        ("tl", "Past reference followed by active immediate threat (tests PAST early-return bug).", "Kanina pa kita hinihintay, bubugbugin kita ngayon na!", "DIRECT_THREAT", "DANGER", 9.0, (7.5, 10.0), False, "grp_mixed_thr2", ["mixed_clause", "adversarial"]),
        ("tl", "Negation followed by active threat (tests NEGATION early-return bug).", "Hindi kita sasaktan ngayon, pero papatayin kita bukas sa labas!", "DIRECT_THREAT", "DANGER", 9.0, (7.0, 10.0), True, "grp_mixed_thr3", ["mixed_clause", "adversarial"]),
        ("tl", "Affection idiom paired with violent threat.", "Mahal kita pero sasapakin kita pag lumapit ka pa sa kanya!", "DIRECT_THREAT", "DANGER", 8.5, (6.5, 9.5), True, "grp_mixed_thr4", ["mixed_clause", "adversarial"]),
        # ASR transcription error variants on threats
        ("tl", "ASR split-word typo ('sa sapakin').", "Sa sapakin kita mamaya sa gate!", "DIRECT_THREAT", "DANGER", 8.5, (7.0, 9.5), True, "grp_asr_thr1", ["asr_error"]),
        ("tl", "ASR typo ('pa patayin').", "Pa patayin kita pag umimik ka pa!", "DIRECT_THREAT", "DANGER", 9.0, (7.0, 10.0), True, "grp_asr_thr2", ["asr_error"]),
        # Indirect / veiled school intimidation
        ("tl", "Veiled campus intimidation forecasting harm.", "Alam mo na kung ano ang aabutin mo paglabas ng gate mamaya.", "DIRECT_THREAT", "THREAT", 6.5, (5.5, 7.8), True, "grp_ind1", ["indirect_intimidation"]),
        ("tl", "Veiled third-party intimidation after class.", "May kakausap sa'yo pagkatapos ng klase.", "DIRECT_THREAT", "THREAT", 6.5, (5.5, 7.8), True, "grp_ind2", ["indirect_intimidation"]),
        ("tl", "Conditional veiled threat.", "Sa susunod na makita kita, ewan ko na lang.", "DIRECT_THREAT", "THREAT", 6.2, (5.0, 7.8), True, "grp_ind3", ["indirect_intimidation"]),
        ("tl", "Unfinished conflict intimidation.", "Hindi pa tayo tapos, tandaan mo yan.", "DIRECT_THREAT", "THREAT", 6.2, (5.0, 7.8), True, "grp_ind4", ["indirect_intimidation"]),
        ("tl", "Ambush threat at school gate.", "Abangan kita sa gate mamaya paglabas mo.", "DIRECT_THREAT", "THREAT", 6.8, (5.5, 7.8), True, "grp_ind5", ["indirect_intimidation"]),
        ("tl", "Warning to prepare for retaliation.", "Humanda ka sa akin mamaya sa labas!", "DIRECT_THREAT", "THREAT", 6.8, (5.5, 7.8), True, "grp_ind6", ["indirect_intimidation"]),
        ("tl", "Retaliation threat ('reresbakan').", "Reresbakan kita kasama ng mga tropa ko!", "DIRECT_THREAT", "THREAT", 7.0, (5.5, 8.5), True, "grp_ind7", ["indirect_intimidation"]),
        ("en", "English veiled after-class threat.", "Wait until after class when we get outside.", "DIRECT_THREAT", "THREAT", 6.5, (5.5, 7.8), True, "grp_ind8", ["indirect_intimidation"]),
        ("en", "English regret threat.", "You'll regret this, just wait and see.", "DIRECT_THREAT", "THREAT", 6.2, (5.0, 7.8), True, "grp_ind9", ["indirect_intimidation"]),
        ("taglish", "Taglish ambush intimidation.", "Wag kang lalabas ng school mag-isa, lagot ka sa akin mamaya.", "DIRECT_THREAT", "THREAT", 6.8, (5.5, 7.8), True, "grp_ind10", ["indirect_intimidation"]),
        ("tl", "Threat of group beating.", "Ipapabugbog kita sa mga tropa ko sa labas!", "DIRECT_THREAT", "DANGER", 8.5, (7.0, 9.5), False, "grp_phys11", ["battery"]),
        ("tl", "Threat to break face.", "Babasagin ko mukha mo pag nakita kita sa hallway!", "DIRECT_THREAT", "DANGER", 8.8, (7.5, 9.8), False, "grp_phys12", ["battery"]),
        ("tl", "Choking threat.", "Sasakalin kita pag di ka tumigil!", "DIRECT_THREAT", "DANGER", 8.8, (7.5, 9.8), False, "grp_phys13", ["battery"]),
        ("taglish", "Slang threat ('yari ka sakin').", "Yari ka sakin paglabas ng gate mamaya, wag kang tatakbo!", "DIRECT_THREAT", "THREAT", 6.8, (5.5, 7.8), True, "grp_ind11", ["indirect_intimidation"]),
        ("en", "English threat to break face.", "I'll break your face if you touch my locker again!", "DIRECT_THREAT", "DANGER", 8.5, (7.5, 9.5), False, "grp_phys14", ["battery"]),
    ]
    for i, (lang, ctx, utt, intent, lvl, sev, sr, rev, grp, etags) in enumerate(threat_items, 1):
        scenarios.append(_txt(
            f"V4-DEV-THR-{i:03d}", "direct_and_indirect_threats", lang, ctx, utt,
            intent, lvl, sev, sr, rev, grp, threat=True, extra_tags=etags
        ))

    # =========================================================================
    # 6. MULTI-TURN CONVERSATIONS (30)
    # =========================================================================
    mt_items = [
        # 1-5: Friendly banter staying benign across turns
        ("taglish", "Mutual friendly banter with 'bakla' and laughter.", [
            ("Hoy, bakla ka! San ka galing?", 0.0, "peer"),
            ("Haha galing akong canteen bes, binilhan kita ng turon!", 4.0, "wearer"),
        ], "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 2.0), False, "grp_mt_bakla_benign", True, False, ["bakla_benign"]),
        ("taglish", "Mutual gaming trash talk between friends.", [
            ("Ang bobo mo sa ML pre haha!", 0.0, "peer"),
            ("Gago ka talaga, 1v1 tayo mamaya sa lunch haha!", 5.0, "wearer"),
        ], "ORDINARY_CONVERSATION", "NORMAL", 1.2, (0.0, 2.5), False, "grp_mt_gaming", True, False, ["gaming_banter"]),
        ("tl", "Ordinary study conversation across 3 turns.", [
            ("Tapos ka na ba sa assignment sa Filipino?", 0.0, "peer"),
            ("Hindi pa, nasa number five pa lang ako.", 6.0, "wearer"),
            ("Tara sabay na tayo magsagot sa library.", 12.0, "peer"),
        ], "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_mt_study", False, False, ["benign"]),
        ("en", "Friendly banter about sports.", [
            ("You totally missed that free throw haha!", 0.0, "peer"),
            ("Shut up, I'll beat you in the next quarter lol!", 4.0, "wearer"),
        ], "ORDINARY_CONVERSATION", "NORMAL", 1.2, (0.0, 2.5), False, "grp_mt_sports", True, False, ["sports_banter"]),
        ("taglish", "Casual chat mentioning 'baon' benignly.", [
            ("Magkano baon mo ngayon?", 0.0, "peer"),
            ("Isang daan lang, hati tayo sa siomai.", 5.0, "wearer"),
        ], "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_mt_baon_benign", False, False, ["benign"]),

        # 6-12: Teasing escalating AFTER request to stop / expression of discomfort
        ("tl", "'Hoy, bakla ka!' followed by request to stop and continued mockery -> harmful.", [
            ("Hoy, bakla ka!", 0.0, "aggressor"),
            ("Tama na please, hindi na nakakatuwa.", 5.0, "wearer"),
            ("Bakla ka naman talaga, ang arte mo, lumayo ka dito!", 10.0, "aggressor"),
        ], "VERBAL_HARASSMENT", "THREAT", 6.8, (5.5, 7.8), True, "grp_mt_bakla_harmful", False, False, ["bakla_harmful", "request_to_stop"]),
        ("taglish", "Victim asks aggressor to stop; aggressor continues insulting.", [
            ("Ang pangit mo talaga, mukha kang ewan.", 0.0, "aggressor"),
            ("Stop it, ayoko na, tigilan mo na ako.", 6.0, "wearer"),
            ("Bobo ka pa, iiyak ka na naman parang bata!", 12.0, "aggressor"),
        ], "VERBAL_HARASSMENT", "THREAT", 7.0, (5.5, 7.8), True, "grp_mt_stop1", False, False, ["request_to_stop", "repeated_harassment"]),
        ("en", "English teasing turns harmful after explicit discomfort.", [
            ("You're such a loser, look at your shoes.", 0.0, "aggressor"),
            ("Please leave me alone, I'm not laughing.", 7.0, "wearer"),
            ("Shut up idiot, nobody cares what you feel!", 13.0, "aggressor"),
        ], "VERBAL_HARASSMENT", "THREAT", 6.8, (5.5, 7.8), True, "grp_mt_stop2", False, False, ["request_to_stop"]),
        ("taglish", "Teasing followed by discomfort and 'joke lang' gaslighting + threat.", [
            ("Ang tanga mo talaga sa klase.", 0.0, "aggressor"),
            ("Hindi na nakakatuwa yan, tigilan mo na.", 5.0, "wearer"),
            ("Sasapakin kita diyan eh, joke lang ang pikon mo!", 11.0, "aggressor"),
        ], "DIRECT_THREAT", "THREAT", 7.2, (5.5, 8.8), True, "grp_mt_stop_joke", False, True, ["request_to_stop", "humor_masked_threat"]),
        ("tl", "Repeated harassment across 3 turns spaced 90s apart (true multi-episode recurrence).", [
            ("Ang bobo mo talaga!", 0.0, "aggressor"),
            ("Wala kang kwenta dito, inutil!", 90.0, "aggressor"),
            ("Pabigat ka lang, pangit mo!", 180.0, "aggressor"),
        ], "VERBAL_HARASSMENT", "THREAT", 7.2, (6.5, 7.8), False, "grp_mt_rep1", False, False, ["repeated_harassment"]),
        ("tl", "Single continuous episode split by 8s firmware cap (turns 7s apart).", [
            ("Ang bobo mo talaga sa math...", 0.0, "aggressor"),
            ("...wala kang kwenta sa group natin!", 7.0, "aggressor"),
        ], "VERBAL_HARASSMENT", "THREAT", 6.0, (5.0, 6.8), False, "grp_mt_split1", False, False, ["split_stream_single_episode"]),
        ("taglish", "Social exclusion continuing after victim asks to join.", [
            ("Pwede ba ako sumali sa group niyo?", 0.0, "wearer"),
            ("Wag ka sumali samin, ang baho mo at pabigat ka lang!", 4.0, "aggressor"),
            ("Alis ka na nga dito, walang may gusto sa'yo!", 9.0, "aggressor"),
        ], "VERBAL_HARASSMENT", "THREAT", 6.8, (5.5, 7.8), False, "grp_mt_excl", False, False, ["exclusion", "repeated_harassment"]),

        # 13-18: Extortion & coercion multi-turn
        ("tl", "Allowance extortion escalating to coercion.", [
            ("Akin na yang baon mo ngayon.", 0.0, "aggressor"),
            ("Wala na akong pera, pamasahe ko na lang to.", 5.0, "wearer"),
            ("Ibigay mo na kundi bubugbugin kita, at huwag kang magsusumbong!", 10.0, "aggressor"),
        ], "DIRECT_THREAT", "DANGER", 8.8, (7.5, 10.0), False, "grp_mt_ext_esc", False, True, ["extortion", "coercion"]),
        ("tl", "Repeated extortion across 2 separate moments (120s apart).", [
            ("Ilabas mo yung pera mo, bilis.", 0.0, "aggressor"),
            ("Araw-araw mo akong babayaran mula bukas.", 120.0, "aggressor"),
        ], "EXTORTION", "THREAT", 7.5, (6.5, 7.8), True, "grp_mt_ext_rep", False, True, ["extortion", "repeated_harassment"]),
        ("taglish", "Coercion to hide earlier bullying.", [
            ("Bakit ka umiiyak?", 0.0, "aggressor"),
            ("Huwag mong sabihin sa teacher o sa guidance, pag nagsumbong ka lagot ka!", 5.0, "aggressor"),
        ], "COERCION", "THREAT", 6.5, (5.5, 7.8), True, "grp_mt_coer1", False, True, ["coercion"]),
        ("en", "English lunch money extortion and silencing.", [
            ("Hand over your lunch money right now.", 0.0, "aggressor"),
            ("Don't tell the teacher or you'll regret it.", 6.0, "aggressor"),
        ], "COERCION", "THREAT", 6.5, (5.5, 7.8), True, "grp_mt_coer_en", False, True, ["extortion", "coercion"]),
        ("tl", "Extortion with victim refusal and veiled threat.", [
            ("Magbayad ka sa akin bago ka dumaan dito.", 0.0, "aggressor"),
            ("Ayoko, pera ko to.", 4.0, "wearer"),
            ("Alam mo na mangyayari sa'yo mamaya sa gate.", 9.0, "aggressor"),
        ], "DIRECT_THREAT", "THREAT", 7.2, (6.0, 7.8), True, "grp_mt_ext_ind", False, True, ["extortion", "indirect_intimidation"]),
        ("taglish", "Repeated indirect intimidation across 2 turns.", [
            ("Hindi pa tayo tapos.", 0.0, "aggressor"),
            ("Abangan kita sa labas pagkatapos ng klase.", 60.0, "aggressor"),
        ], "DIRECT_THREAT", "THREAT", 7.6, (6.5, 7.8), True, "grp_mt_ind_rep", False, True, ["indirect_intimidation"]),

        # 19-24: Reported speech & past-incident multi-turn discussions
        ("tl", "Student reporting bullying to a friend/counselor.", [
            ("Bakit ka kinakabahan?", 0.0, "peer"),
            ("Sinabi niya na bubugbugin daw niya ako mamaya sa gate.", 5.0, "wearer"),
        ], "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_mt_rep_speech1", False, False, ["reported_speech"]),
        ("taglish", "Student recounting yesterday's hallway altercation.", [
            ("Anong nangyari sa braso mo?", 0.0, "peer"),
            ("Sinapak ako nung taga-Section C kahapon sa labas.", 4.0, "wearer"),
        ], "PAST_INCIDENT", "WARNING", 3.5, (2.5, 5.0), True, "grp_mt_past1", False, False, ["past_incident"]),
        ("en", "Student reporting a classmate's threat.", [
            ("Are you okay?", 0.0, "peer"),
            ("He told me he would beat me up after school.", 5.0, "wearer"),
        ], "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_mt_rep_en", False, False, ["reported_speech"]),
        ("tl", "Quoting a movie line in class discussion.", [
            ("Anong linya yung paborito mo sa pelikula?", 0.0, "peer"),
            ("Sabi niya doon sa eksena papatayin daw niya yung kontrabida.", 6.0, "wearer"),
        ], "REPORTED_THREAT", "WARNING", 3.0, (1.0, 5.5), True, "grp_mt_quote", False, False, ["quoted_speech"]),
        ("taglish", "De-escalation and reassurance after misunderstanding.", [
            ("Galit ka ba sa akin?", 0.0, "wearer"),
            ("Hindi ah, wag ka mag-alala, hindi kita sasaktan.", 4.0, "peer"),
        ], "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_mt_neg1", False, False, ["negation"]),
        ("tl", "Dream story shared between friends.", [
            ("Ang sama ng panaginip ko kagabi.", 0.0, "wearer"),
            ("Napanaginipan kong may humahabol sakin sa school.", 5.0, "wearer"),
        ], "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_mt_dream", False, False, ["hypothetical"]),

        # 25-30: Escalation to physical danger & ambiguous multi-turn
        ("tl", "Harassment escalating rapidly to direct physical threat.", [
            ("Ang yabang mo ha, bobo ka naman!", 0.0, "aggressor"),
            ("Wala naman akong ginagawa sa'yo!", 4.0, "wearer"),
            ("Sasapakin kita ngayon na!", 8.0, "aggressor"),
        ], "DIRECT_THREAT", "DANGER", 9.0, (8.0, 10.0), False, "grp_mt_esc_danger", False, True, ["escalation", "battery"]),
        ("taglish", "Escalation from exclusion to lethal threat.", [
            ("Umalis ka nga dito, pangit mo!", 0.0, "aggressor"),
            ("Dito yung upuan ko eh.", 4.0, "wearer"),
            ("Papatayin kita pag hindi ka umalis diyan!", 9.0, "aggressor"),
        ], "DIRECT_THREAT", "DANGER", 9.2, (8.0, 10.0), False, "grp_mt_esc_lethal", False, True, ["escalation", "lethal"]),
        ("en", "English argument escalating to physical assault threat.", [
            ("Give me back my notebook!", 0.0, "wearer"),
            ("Make me, you idiot!", 4.0, "aggressor"),
            ("I will punch you right now if you don't back off!", 9.0, "aggressor"),
        ], "DIRECT_THREAT", "DANGER", 8.8, (8.0, 10.0), False, "grp_mt_en_danger", False, True, ["escalation", "battery"]),
        ("tl", "Ambiguous tense exchange without explicit threat or laughter.", [
            ("Hoy, bakit mo ako tinitignan?", 0.0, "unknown"),
            ("Wala naman.", 4.0, "wearer"),
            ("Tignan natin mamaya.", 8.0, "unknown"),
        ], "AMBIGUOUS_CONTEXT", "WARNING", 3.5, (2.0, 5.5), True, "grp_mt_ambig1", False, False, ["ambiguous", "insufficient_context"]),
        ("taglish", "Ambiguous borrowing vs taking item.", [
            ("Pahiram ng phone mo sandali.", 0.0, "unknown"),
            ("Kailangan ko pa kasi.", 4.0, "wearer"),
            ("Akin na nga yan, bilis.", 8.0, "unknown"),
        ], "AMBIGUOUS_CONTEXT", "WARNING", 3.5, (2.0, 5.5), True, "grp_mt_ambig2", False, False, ["ambiguous", "insufficient_context"]),
        ("tl", "Repeated harassment across 4 turns with ASR noise.", [
            ("Ambobo mo talaga.", 0.0, "aggressor"),
            ("Wala kang kuwenta!", 50.0, "aggressor"),
            ("Tanga mo naman!", 110.0, "aggressor"),
            ("Inutil ka talaga, umalis ka dito!", 170.0, "aggressor"),
        ], "VERBAL_HARASSMENT", "THREAT", 7.2, (6.5, 7.8), False, "grp_mt_rep_asr", False, False, ["repeated_harassment", "asr_error"]),
    ]
    for i, (lang, ctx, turns, intent, lvl, sev, sr, rev, grp, tease, thr, etags) in enumerate(mt_items, 1):
        scenarios.append(_mt(
            f"V4-DEV-MT-{i:03d}", lang, ctx, turns, intent, lvl, sev, sr, rev, grp,
            teasing=tease, threat=thr, extra_tags=etags
        ))

    # =========================================================================
    # 7. REPORTED SPEECH (20)
    # =========================================================================
    reported_items = [
        ("tl", "Reporting a death threat made by another student.", "Sinabi niya na papatayin niya ako paglabas.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep1"),
        ("tl", "Reporting group battery threat ('daw').", "Sabi nila bubugbugin daw ako mamaya sa gate.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep2"),
        ("en", "Reporting threat in English.", "He said that he would beat me up after class.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep3"),
        ("tl", "Reporting someone threatened to punch them.", "Nagbanta siya na sasapakin niya ako bukas.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep4"),
        ("taglish", "Reporting classmate's extortion.", "Kwento ng kaklase ko na kinukuha raw ng senior yung baon niya.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep5"),
        ("tl", "Hearing rumor of ambush ('aabangan daw').", "Aabangan daw nila si Mark sa labas mamayang hapon.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep6"),
        ("en", "Reporting quoted threat to counselor.", "Someone told me they're going to jump me at the gate.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep7"),
        ("taglish", "Reporting verbal bullying about a friend.", "Sabi niya ang bobo at pangit daw ni Liza sa group chat.", "REPORTED_THREAT", "THREAT", 4.5, (3.5, 6.0), True, "grp_rep8"),
        ("tl", "Reporting threat with 'raw'.", "Sasapakin raw niya ako pag nagsumbong ako sa teacher.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep9"),
        ("en", "Reporting third-party threat.", "She threatened that she would ruin my things if I sit there.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep10"),
        ("tl", "Reporting rumor of shooting ('babarilin daw').", "Balita ko na nagbanta sila na aabangan yung grade eight.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep11"),
        ("taglish", "Reporting quoted homophobic harassment.", "Sinabi nung lalaki na 'hoy bakla ka, lumayas ka dito' kay Paolo.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep12"),
        ("tl", "Quoting what a bully told them yesterday.", "Sabi niya sakin kahapon wala raw akong kwenta.", "REPORTED_THREAT", "THREAT", 4.5, (3.5, 6.0), True, "grp_rep13"),
        ("en", "Quoting a text message threat.", "He literally texted 'I will punch your face' to my friend.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep14"),
        ("taglish", "Reporting coercion attempt.", "Sinabi nila na wag daw kami magsumbong sa guidance.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep15"),
        ("tl", "Reporting threat heard in hallway.", "Narinig ko sabi niya bubugbugin daw niya yung bagong lipat.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep16"),
        ("en", "Reporting news about another school.", "They said someone got threatened near the bus stop last week.", "REPORTED_THREAT", "WARNING", 3.5, (2.0, 5.5), True, "grp_rep17"),
        ("taglish", "Reporting classmate's story.", "Kwento nung isa na hinihingan daw sila ng bente araw-araw.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep18"),
        ("tl", "Mixed reported speech PLUS active self-threat (adversarial!).", "Sabi niya bobo ka raw, at sasapakin din kita ngayon!", "DIRECT_THREAT", "DANGER", 8.5, (6.5, 9.5), True, "grp_rep_adv1"),
        ("taglish", "Reporting threat with ASR spelling slip ('nag banta').", "Nag banta siya na papatayin daw niya ako.", "REPORTED_THREAT", "THREAT", 5.0, (4.0, 6.0), True, "grp_rep_asr"),
    ]
    for i, (lang, ctx, utt, intent, lvl, sev, sr, rev, grp) in enumerate(reported_items, 1):
        thr = intent == "DIRECT_THREAT"
        etags = ["adversarial", "mixed_clause"] if thr else (["asr_error"] if "ASR" in ctx else ["reported_speech"])
        scenarios.append(_txt(
            f"V4-DEV-REP-{i:03d}", "reported_speech", lang, ctx, utt,
            intent, lvl, sev, sr, rev, grp, threat=thr, extra_tags=etags
        ))

    # =========================================================================
    # 8. NEGATIONS AND HYPOTHETICALS (20)
    # =========================================================================
    neg_hyp_items = [
        ("tl", "Explicit reassurance of non-harm.", "Hindi kita sasaktan, mag-usap lang tayo nang maayos.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg1"),
        ("tl", "Negated lethal verb.", "Di kita papatayin, kumalma ka nga.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg2"),
        ("tl", "Disclaiming any harmful intent.", "Wala akong gagawing masama sa'yo, promise.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg3"),
        ("en", "English explicit non-harm.", "I will not hurt you, I'm just trying to help.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg4"),
        ("tl", "Stating peaceful stance.", "Hindi ako mananakit ng kaklase, ayoko ng gulo.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg5"),
        ("en", "English promise not to fight.", "I won't punch him even if he annoys me.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg6"),
        ("tl", "Negated beating.", "Hinde kita bubugbugin, tigilan mo na pag-iyak.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg7"),
        ("taglish", "ASR split negation ('di ki ta').", "Di ki ta gagalawin, pramis.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 2.5), False, "grp_neg_asr"),
        ("tl", "Describing a bad dream.", "Napanaginipan kong namatay yung aso namin.", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp1"),
        ("tl", "Speculative 'what if' question.", "Paano kung may biglang sumigaw habang nag-eexam?", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp2"),
        ("en", "English 'what if' story plot.", "What if the villain in our play steals the treasure?", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp3"),
        ("tl", "Roleplay disclaimer ('kunwari lang').", "Kunwari lang na nag-aaway tayo sa roleplay ng Noli Me Tangere.", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp4"),
        ("en", "Dream narrative in English.", "I dreamed that we were running away from a giant storm.", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp5"),
        ("tl", "Conditional hypothetical ('kung sakali').", "Kung sakaling may mang-away, isumbong natin agad sa guidance.", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp6"),
        ("taglish", "Speculative 'pano kung'.", "Pano kung ma-cancel yung klase bukas dahil sa bagyo?", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp7"),
        ("tl", "Talking about a nightmare.", "Panaginip lang pala na nasunog yung school.", "HYPOTHETICAL_THREAT", "NORMAL", 1.8, (0.0, 2.5), False, "grp_hyp8"),
        ("en", "English disclaimer in debate.", "I don't want to harm anyone's feelings during the debate.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg8"),
        ("tl", "Adversarial veiled hypothetical threat (needs human review!).", "Paano kung bigla na lang kita sapakin ngayon?", "DIRECT_THREAT", "THREAT", 6.0, (4.0, 7.8), True, "grp_hyp_adv1"),
        ("en", "Adversarial veiled English hypothetical threat.", "What if I break your nose right now?", "DIRECT_THREAT", "THREAT", 6.5, (4.0, 7.8), True, "grp_hyp_adv2"),
        ("tl", "Negating violence while reassuring.", "Hindi namin sila aawayin, gusto lang namin mag-sorry.", "NEGATED_THREAT", "NORMAL", 1.2, (0.0, 1.9), False, "grp_neg9"),
    ]
    for i, (lang, ctx, utt, intent, lvl, sev, sr, rev, grp) in enumerate(neg_hyp_items, 1):
        thr = intent == "DIRECT_THREAT"
        etags = ["adversarial", "veiled_hypothetical"] if thr else (["asr_error"] if "ASR" in ctx else ["negation_hypothetical"])
        scenarios.append(_txt(
            f"V4-DEV-NH-{i:03d}", "negation_and_hypothetical", lang, ctx, utt,
            intent, lvl, sev, sr, rev, grp, threat=thr, extra_tags=etags
        ))

    # =========================================================================
    # 9. SARCASM AND IDIOMS (20)
    # =========================================================================
    sarc_idiom_items = [
        ("tl", "Tagalog romantic idiom ('patay na patay').", "Patay na patay ako sa kanya mula pa nung Grade 8!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id1"),
        ("taglish", "Academic hyperbole ('nakakamatay ang exam').", "Grabe, nakakamatay yung exam sa Calculus kanina!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id2"),
        ("tl", "Laughter hyperbole ('mamatay sa tawa').", "Mamatay ako sa tawa sa video na pinakita mo!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id3"),
        ("en", "English hyperbole ('dying of laughter').", "I'm literally dying of laughter right now!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id4"),
        ("tl", "Academic determination ('babawi ako').", "Babawi ako sa susunod na quiz, mag-aaral na ako nang mabuti.", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id5"),
        ("tl", "Hunger hyperbole.", "Mamatay na ako sa gutom, tara na sa canteen!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id6"),
        ("taglish", "Heat hyperbole.", "Nakakamatay yung init dito sa covered court!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id7"),
        ("en", "English idiom ('kill it' = do great).", "You're going to kill it at the speech contest today!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id8"),
        ("en", "English idiom ('break a leg').", "Break a leg on your theater audition later!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id9"),
        ("tl", "Idiom ('dugo ang ilong' = hard English).", "Dugo na ilong ko sa kaka-English sa debate natin!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id10"),
        ("taglish", "Benign reassurance with 'biro lang'.", "Wag ka mag-alala, biro lang yung sinabi kong may surprise quiz!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id11"),
        ("en", "Benign 'killing time'.", "We're just killing time at the bench before Math starts.", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id12"),
        ("taglish", "Fatigue hyperbole.", "Nakakamatay yung pagod after ng PE running test.", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id13"),
        ("tl", "Affection expression.", "Crush kita dati pa, charot lang haha!", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id14"),
        ("taglish", "Sarcastic backhanded insult ('ang talino mo' used cruelly).", "Wow, ang talino mo naman pala, zero ka na naman sa quiz, nakakahiya!", "VERBAL_HARASSMENT", "WARNING", 3.5, (2.5, 6.0), True, "grp_sarc1"),
        ("en", "Sarcastic demeaning praise.", "Oh great job genius, you ruined the whole group project again.", "VERBAL_HARASSMENT", "WARNING", 3.8, (2.5, 6.0), True, "grp_sarc2"),
        ("taglish", "Sarcastic 'dasurv' mocking victim's misfortune.", "Dasurv mo mapagalitan, ang bobo mo kasi eh!", "VERBAL_HARASSMENT", "THREAT", 5.5, (4.0, 7.0), True, "grp_sarc3"),
        ("tl", "Ambiguous sarcasm ('ang galing mo naman').", "Ang galing mo naman talaga.", "AMBIGUOUS_CONTEXT", "WARNING", 2.5, (1.0, 3.9), True, "grp_sarc4"),
        ("taglish", "Benign sarcasm about rain.", "Ang ganda ng panahon grabe, baha na sa quadrangle.", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_sarc5"),
        ("tl", "Idiom ('sunog kilay' = studying hard).", "Sunog kilay na naman tayo mamayang gabi para sa finals.", "ORDINARY_CONVERSATION", "NORMAL", 1.0, (0.0, 1.9), False, "grp_id15"),
    ]
    for i, (lang, ctx, utt, intent, lvl, sev, sr, rev, grp) in enumerate(sarc_idiom_items, 1):
        etags = ["sarcasm"] if "sarc" in grp else ["idiom"]
        scenarios.append(_txt(
            f"V4-DEV-SI-{i:03d}", "sarcasm_and_idioms", lang, ctx, utt,
            intent, lvl, sev, sr, rev, grp, extra_tags=etags
        ))

    # =========================================================================
    # 10. EXTORTION AND COERCION (15)
    # =========================================================================
    ext_coer_items = [
        ("tl", "Direct allowance extortion.", "Akin na yang baon mo ngayon!", "EXTORTION", "THREAT", 6.8, (5.0, 7.8), True, "grp_ext1"),
        ("tl", "Recurring daily extortion demand.", "Araw-araw mo akong babayaran ng bente!", "EXTORTION", "THREAT", 6.8, (5.0, 7.8), True, "grp_ext2"),
        ("tl", "Forcing surrender of money.", "Ilabas mo na yung pera mo sa bulsa, bilis!", "EXTORTION", "THREAT", 6.5, (5.0, 7.8), True, "grp_ext3"),
        ("tl", "Demanding allowance with threat.", "Ibigay mo sakin allowance mo kung ayaw mong masaktan.", "EXTORTION", "THREAT", 7.2, (5.5, 7.8), True, "grp_ext4"),
        ("en", "English lunch money extortion.", "Give me your lunch money or else!", "EXTORTION", "THREAT", 6.8, (5.0, 7.8), True, "grp_ext5"),
        ("en", "English 'pay up' extortion.", "Pay up or else you're not leaving this hallway.", "EXTORTION", "THREAT", 7.0, (5.5, 7.8), True, "grp_ext6"),
        ("taglish", "Hallway toll extortion ('tax').", "Magbayad ka ng tax sa akin araw-araw bago ka dumaan dito.", "EXTORTION", "THREAT", 6.8, (5.0, 7.8), True, "grp_ext7"),
        ("taglish", "ASR typo on 'baon mo' ('bawn mo').", "Akin na yang bawn mo kundi lagot ka!", "EXTORTION", "THREAT", 6.8, (5.0, 7.8), True, "grp_ext_asr"),
        ("tl", "Secrecy coercion against telling teacher.", "Huwag mong sabihin sa teacher yung nangyari!", "COERCION", "THREAT", 5.8, (4.5, 7.5), True, "grp_coer1"),
        ("tl", "Warning against snitching.", "Huwag kang magsusumbong sa guidance o sa magulang mo!", "COERCION", "THREAT", 6.0, (4.5, 7.5), True, "grp_coer2"),
        ("tl", "Conditional retaliation for reporting.", "Pag nagsumbong ka, alam mo na mangyayari sa'yo!", "COERCION", "THREAT", 6.8, (5.0, 7.8), True, "grp_coer3"),
        ("tl", "Daring victim not to report.", "Subukan mong magsumbong sa dean, tingnan natin!", "COERCION", "THREAT", 6.5, (5.0, 7.8), True, "grp_coer4"),
        ("en", "English anti-snitching coercion.", "Don't dare tell the principal about this.", "COERCION", "THREAT", 5.8, (4.5, 7.5), True, "grp_coer5"),
        ("en", "English conditional snitch warning.", "If you snitch to anyone, you'll be sorry.", "COERCION", "THREAT", 6.5, (5.0, 7.8), True, "grp_coer6"),
        ("taglish", "Extortion masked with 'joke lang' (adversarial!).", "Ilabas mo na yung baon mo ngayon, joke lang!", "EXTORTION", "THREAT", 6.5, (4.5, 7.8), True, "grp_ext_joke"),
    ]
    for i, (lang, ctx, utt, intent, lvl, sev, sr, rev, grp) in enumerate(ext_coer_items, 1):
        etags = ["adversarial", "humor_masked_extortion"] if "joke" in grp else (["asr_error"] if "asr" in grp else [])
        scenarios.append(_txt(
            f"V4-DEV-EC-{i:03d}", "extortion_and_coercion", lang, ctx, utt,
            intent, lvl, sev, sr, rev, grp, threat=True, extra_tags=etags
        ))

    return scenarios


def main() -> int:
    scenarios = build_scenarios()
    payload = {
        "schema_version": "1.0.0",
        "dataset_name": "securelink_v4_dev_300",
        "split": "dev",
        "description": (
            "300 synthetic, provisionally labeled Filipino/English/Taglish development and "
            "challenge-test scenarios for SecureLink V4. All labels are synthetic and provisional; "
            "independently prepared human-reviewed scenarios are reserved for final held-out evaluation."
        ),
        "scenarios": scenarios,
    }
    # Validate strictly via EvalDataset Pydantic schema before writing
    ds = EvalDataset.model_validate(payload)
    out_path = Path(__file__).resolve().parent / "datasets" / "v4_dev_300.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ds.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(ds.scenarios)} validated scenarios to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
