// ICU 60 → ICU 70 compatibility shim
// Maps icu_60 symbols (needed by EzSim's libboost_regex.so.1.75.0) to icu_70
//
// Build:
//   g++ -shared -fPIC -o /tmp/libicu60shim.so icu60shim.cpp -licuuc -licui18n
//
// Usage:
//   LD_PRELOAD=/tmp/libicu60shim.so <your-command>

__asm__(
    ".text\n"
    // C++ methods: icu_60::Locale
    ".globl _ZN6icu_606LocaleC1Ev\n"
    ".type _ZN6icu_606LocaleC1Ev, @function\n"
    "_ZN6icu_606LocaleC1Ev:\n"
    "    jmp _ZN6icu_706LocaleC1Ev@PLT\n"

    ".globl _ZN6icu_606LocaleC1ERKS0_\n"
    ".type _ZN6icu_606LocaleC1ERKS0_, @function\n"
    "_ZN6icu_606LocaleC1ERKS0_:\n"
    "    jmp _ZN6icu_706LocaleC1ERKS0_@PLT\n"

    ".globl _ZN6icu_606LocaleD1Ev\n"
    ".type _ZN6icu_606LocaleD1Ev, @function\n"
    "_ZN6icu_606LocaleD1Ev:\n"
    "    jmp _ZN6icu_706LocaleD1Ev@PLT\n"

    // C++ method: icu_60::Collator::createInstance
    ".globl _ZN6icu_608Collator14createInstanceERKNS_6LocaleER10UErrorCode\n"
    ".type _ZN6icu_608Collator14createInstanceERKNS_6LocaleER10UErrorCode, @function\n"
    "_ZN6icu_608Collator14createInstanceERKNS_6LocaleER10UErrorCode:\n"
    "    jmp _ZN6icu_708Collator14createInstanceERKNS_6LocaleER10UErrorCode@PLT\n"

    // C-level ICU functions (versioned with _60 suffix)
    ".globl u_isspace_60\n"
    ".type u_isspace_60, @function\n"
    "u_isspace_60:\n"
    "    jmp u_isspace_70@PLT\n"

    ".globl u_isblank_60\n"
    ".type u_isblank_60, @function\n"
    "u_isblank_60:\n"
    "    jmp u_isblank_70@PLT\n"

    ".globl u_charType_60\n"
    ".type u_charType_60, @function\n"
    "u_charType_60:\n"
    "    jmp u_charType_70@PLT\n"

    ".globl u_digit_60\n"
    ".type u_digit_60, @function\n"
    "u_digit_60:\n"
    "    jmp u_digit_70@PLT\n"

    ".globl u_tolower_60\n"
    ".type u_tolower_60, @function\n"
    "u_tolower_60:\n"
    "    jmp u_tolower_70@PLT\n"

    ".globl u_charFromName_60\n"
    ".type u_charFromName_60, @function\n"
    "u_charFromName_60:\n"
    "    jmp u_charFromName_70@PLT\n"
);
