package com.unboundinfotech.keyboard

import java.util.Locale

/**
 * On-device Unbound Keyboard brain. Same spelling / grammar map as
 * backend/services/writing_local.py. No network. Password boxes never
 * reach this code.
 */
object LocalProofread {
    private const val MAX_CHARS = 8000
    private const val MAX_ISSUES = 20
    private const val FILLER_MIN = 3

    private val SPELLING = mapOf(
        "teh" to "the",
        "recieve" to "receive",
        "recieved" to "received",
        "seperate" to "separate",
        "seperated" to "separated",
        "definately" to "definitely",
        "occured" to "occurred",
        "occurence" to "occurrence",
        "untill" to "until",
        "wich" to "which",
        "becuase" to "because",
        "becasue" to "because",
        "adress" to "address",
        "tommorrow" to "tomorrow",
        "tmorow" to "tomorrow",
        "tomorow" to "tomorrow",
        "enviroment" to "environment",
        "goverment" to "government",
        "goverment's" to "government's",
        "accomodate" to "accommodate",
        "embarass" to "embarrass",
        "existince" to "existence",
        "independant" to "independent",
        "priviledge" to "privilege",
        "neccessary" to "necessary",
        "occassion" to "occasion",
        "recomend" to "recommend",
        "succesful" to "successful",
        "untited" to "united",
        "usefull" to "useful",
        "writting" to "writing",
        "begining" to "beginning",
        "buisness" to "business",
        "calender" to "calendar",
        "collegue" to "colleague",
        "comming" to "coming",
        "completly" to "completely",
        "concious" to "conscious",
        "curiousity" to "curiosity",
        "dissapoint" to "disappoint",
        "existance" to "existence",
        "familar" to "familiar",
        "finaly" to "finally",
        "foriegn" to "foreign",
        "freind" to "friend",
        "happend" to "happened",
        "harrass" to "harass",
        "immediatly" to "immediately",
        "knowlege" to "knowledge",
        "liason" to "liaison",
        "maintainance" to "maintenance",
        "mispell" to "misspell",
        "noticable" to "noticeable",
        "occassionally" to "occasionally",
        "persue" to "pursue",
        "posession" to "possession",
        "prefered" to "preferred",
        "publically" to "publicly",
        "realy" to "really",
        "refered" to "referred",
        "relavant" to "relevant",
        "remeber" to "remember",
        "resistence" to "resistance",
        "saftey" to "safety",
        "seige" to "siege",
        "sentance" to "sentence",
        "sieze" to "seize",
        "similiar" to "similar",
        "speach" to "speech",
        "sucess" to "success",
        "suprise" to "surprise",
        "thier" to "their",
        "truely" to "truly",
        "unfortunatly" to "unfortunately",
        "usally" to "usually",
        "wether" to "whether",
        "whereever" to "wherever",
        "alot" to "a lot",
        "alright" to "all right",
        "couldnt" to "couldn't",
        "didnt" to "didn't",
        "doesnt" to "doesn't",
        "dont" to "don't",
        "isnt" to "isn't",
        "wasnt" to "wasn't",
        "werent" to "weren't",
        "wont" to "won't",
        "wouldnt" to "wouldn't",
        "cant" to "can't",
        "havent" to "haven't",
        "hasnt" to "hasn't",
        "hadnt" to "hadn't",
        "youre" to "you're",
        "theyre" to "they're",
        "thats" to "that's",
        "whats" to "what's",
        "wheres" to "where's",
        "ive" to "I've",
        "im" to "I'm",
        "weve" to "we've",
        "theyve" to "they've",
        "shouldve" to "should've",
        "wouldve" to "would've",
        "couldve" to "could've",
    )

    private val PHRASE_FIXES = listOf(
        Triple("\\bshould of\\b", "should have", "Use 'should have', not 'should of'."),
        Triple("\\bcould of\\b", "could have", "Use 'could have', not 'could of'."),
        Triple("\\bwould of\\b", "would have", "Use 'would have', not 'would of'."),
        Triple("\\bmight of\\b", "might have", "Use 'might have', not 'might of'."),
        Triple("\\bmust of\\b", "must have", "Use 'must have', not 'must of'."),
        Triple("\\bits a\\b", "it's a", "'It's' means it is."),
        Triple("\\bits an\\b", "it's an", "'It's' means it is."),
        Triple("\\bits the\\b", "it's the", "'It's' means it is."),
        Triple("\\bit's own\\b", "its own", "'Its' is the possessive — no apostrophe."),
        Triple("\\bit's way\\b", "its way", "'Its' is the possessive — no apostrophe."),
        Triple("\\byour welcome\\b", "you're welcome", "'You're' means you are."),
        Triple("\\byour right\\b", "you're right", "'You're' means you are — unless you mean belonging to you."),
        Triple("\\btheir is\\b", "there is", "'There is' points to a place or fact."),
        Triple("\\btheir are\\b", "there are", "'There are' points to a place or fact."),
        Triple("\\bthere going\\b", "they're going", "'They're' means they are."),
        Triple("\\bthey're house\\b", "their house", "'Their' is the possessive."),
        Triple("\\bthey're car\\b", "their car", "'Their' is the possessive."),
        Triple("\\bto to\\b", "to", "That word was typed twice."),
        Triple("\\bthe the\\b", "the", "That word was typed twice."),
        Triple("\\ba a\\b", "a", "That word was typed twice."),
        Triple("\\band and\\b", "and", "That word was typed twice."),
    )

    private val FILLERS = mapOf(
        "just" to listOf("simply", "only"),
        "really" to listOf("truly", "genuinely"),
        "very" to listOf("especially", "rather"),
        "actually" to listOf("in fact"),
        "literally" to listOf(),
        "basically" to listOf("simply"),
        "honestly" to listOf("frankly"),
        "maybe" to listOf("perhaps", "possibly"),
        "stuff" to listOf("the details", "what happened"),
        "things" to listOf("the details", "what happened"),
        "amazing" to listOf("wonderful", "striking", "kind"),
        "great" to listOf("good", "fine", "glad"),
        "nice" to listOf("kind", "warm", "pleasant"),
        "important" to listOf("needed", "pressing"),
        "utilize" to listOf("use"),
        "leverage" to listOf("use"),
    )

    private val WORD_RE = Regex("[A-Za-z][A-Za-z']*")
    private val CARD_RE = Regex("\\b(?:\\d[ -]?){13,19}\\b")
    private val SSN_RE = Regex("\\b\\d{3}-\\d{2}-\\d{4}\\b")
    private val PASSWORD_RE = Regex(
        "(?i)\\b(?:password|passwd|passcode|pin|ssn|social security|cvv|cvc|routing number)\\b\\s*[:=]",
    )
    private val SECRETISH_RE = Regex(
        "(?i)\\b(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\\b",
    )
    private val REPEAT_RE = Regex("\\b([A-Za-z']+)\\s+\\1\\b", RegexOption.IGNORE_CASE)
    private val LONE_I_RE = Regex("(?:^|[.!?]\\s+)(i)(?=\\s)")

    fun looksSecret(text: String): Boolean {
        val blob = text
        if (blob.isBlank()) return false
        if (PASSWORD_RE.containsMatchIn(blob)) return true
        if (SSN_RE.containsMatchIn(blob)) return true
        if (SECRETISH_RE.containsMatchIn(blob)) return true
        val digits = blob.filter { it.isDigit() }
        if (digits.length >= 13 && CARD_RE.containsMatchIn(blob)) return true
        return false
    }

    private fun matchCase(src: String, repl: String): String {
        if (src.isEmpty() || repl.isEmpty()) return repl
        if (src.all { it.isUpperCase() || !it.isLetter() } && src.any { it.isLetter() } && src == src.uppercase(Locale.US)) {
            return repl.uppercase(Locale.US)
        }
        if (src[0].isUpperCase()) {
            return repl[0].uppercaseChar() + repl.substring(1)
        }
        return repl
    }

    fun proofread(text: String): ProofreadResult {
        val original = text
        if (looksSecret(original)) {
            return ProofreadResult(
                secret = true,
                corrected = original,
                styleNote = "That looks private — a password, a card, or a number that should stay with you. I will not read it.",
                issues = emptyList(),
            )
        }
        val clipped = if (original.length > MAX_CHARS) original.substring(0, MAX_CHARS) else original
        val issues = mutableListOf<WritingIssue>()
        val covered = mutableListOf<Pair<Int, Int>>()
        fun overlaps(a: Int, b: Int): Boolean = covered.any { (s, e) -> !(b <= s || a >= e) }

        for ((pattern, repl, note) in PHRASE_FIXES) {
            val re = Regex(pattern, RegexOption.IGNORE_CASE)
            for (m in re.findAll(clipped)) {
                val range = m.range
                val start = range.first
                val end = range.last + 1
                val raw = m.value
                issues.add(
                    WritingIssue(
                        start = start,
                        end = end,
                        kind = "grammar",
                        text = raw,
                        suggestions = listOf(matchCase(raw, repl)),
                        note = note,
                        auto = true,
                    ),
                )
                covered.add(start to end)
                if (issues.size >= MAX_ISSUES) break
            }
            if (issues.size >= MAX_ISSUES) break
        }

        val fillerHits = mutableMapOf<String, Int>()
        for (m in WORD_RE.findAll(clipped)) {
            val key = m.value.lowercase(Locale.US)
            if (key in FILLERS) fillerHits[key] = (fillerHits[key] ?: 0) + 1
        }

        for (m in WORD_RE.findAll(clipped)) {
            if (issues.size >= MAX_ISSUES) break
            val start = m.range.first
            val end = m.range.last + 1
            val raw = m.value
            if (overlaps(start, end)) continue
            val key = raw.lowercase(Locale.US)
            val fixWord = SPELLING[key] ?: continue
            if (fixWord.lowercase(Locale.US) == key) continue
            val fix = matchCase(raw, fixWord)
            if (fix == raw) continue
            issues.add(
                WritingIssue(
                    start = start,
                    end = end,
                    kind = "spelling",
                    text = raw,
                    suggestions = listOf(fix),
                    note = "Did you mean '$fix'?",
                    auto = true,
                ),
            )
            covered.add(start to end)
        }

        for (m in REPEAT_RE.findAll(clipped)) {
            if (issues.size >= MAX_ISSUES) break
            val start = m.range.first
            val end = m.range.last + 1
            if (overlaps(start, end)) continue
            val word = m.groupValues[1]
            issues.add(
                WritingIssue(
                    start = start,
                    end = end,
                    kind = "grammar",
                    text = m.value,
                    suggestions = listOf(word),
                    note = "That word was typed twice.",
                    auto = true,
                ),
            )
            covered.add(start to end)
        }

        for (m in LONE_I_RE.findAll(clipped)) {
            if (issues.size >= MAX_ISSUES) break
            val g = m.groups[1] ?: continue
            val start = g.range.first
            val end = g.range.last + 1
            if (overlaps(start, end)) continue
            issues.add(
                WritingIssue(
                    start = start,
                    end = end,
                    kind = "grammar",
                    text = "i",
                    suggestions = listOf("I"),
                    note = "Capital I when you mean yourself.",
                    auto = true,
                ),
            )
            covered.add(start to end)
        }

        for ((word, n) in fillerHits) {
            if (n < FILLER_MIN || issues.size >= MAX_ISSUES) continue
            val alts = FILLERS[word] ?: emptyList()
            var last: MatchResult? = null
            for (m in WORD_RE.findAll(clipped)) {
                if (m.value.lowercase(Locale.US) == word) last = m
            }
            if (last == null) continue
            issues.add(
                WritingIssue(
                    start = last.range.first,
                    end = last.range.last + 1,
                    kind = "style",
                    text = last.value,
                    suggestions = alts,
                    note = "You used '$word' $n times here. A different word (or none) often sounds more like you.",
                    auto = false,
                ),
            )
        }

        issues.sortBy { it.start }
        val trimmed = issues.take(MAX_ISSUES)
        val corrected = applyAutos(clipped, trimmed)
        val spellingFlags = trimmed.any { it.kind == "spelling" || it.kind == "grammar" }
        val habitFlags = trimmed.any { it.kind == "style" || it.kind == "habit" }
        val bits = mutableListOf<String>()
        if (spellingFlags) bits.add("I marked spelling and little grammar slips.")
        if (habitFlags) bits.add("A few words you lean on are highlighted — tap one for a swap that still sounds like you.")
        if (bits.isEmpty()) bits.add("Looks clean. Keep going.")
        return ProofreadResult(
            secret = false,
            corrected = corrected,
            styleNote = bits.joinToString(" "),
            issues = trimmed,
        )
    }

    private fun applyAutos(text: String, issues: List<WritingIssue>): String {
        var out = text
        val autos = issues.filter { it.auto && it.suggestions.isNotEmpty() }.sortedByDescending { it.start }
        val used = mutableListOf<Pair<Int, Int>>()
        for (item in autos) {
            val start = item.start
            val end = item.end
            if (used.any { (a, b) -> !(end <= a || start >= b) }) continue
            if (start < 0 || end > out.length || start >= end) continue
            out = out.substring(0, start) + item.suggestions[0] + out.substring(end)
            used.add(start to end)
        }
        return out
    }
}

