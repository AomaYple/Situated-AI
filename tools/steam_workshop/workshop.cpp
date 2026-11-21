// Windows x64 Workshop helper, compiled against the Steamworks 1.53a headers.
#include <windows.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

#include "isteamugc.h"
#include "isteamuser.h"
#include "isteamutils.h"

S_API bool S_CALLTYPE SteamAPI_Init();
S_API void S_CALLTYPE SteamAPI_Shutdown();

namespace {
constexpr AppId_t app_id = 529340;
static_assert(sizeof(void*) == 8);
static_assert(sizeof(SteamUGCDetails_t) == 9776);
static_assert(sizeof(SteamUGCQueryCompleted_t) == 280);
static_assert(sizeof(SubmitItemUpdateResult_t) == 16);
static_assert(k_cchPublishedDocumentDescriptionMax == 8000);

struct Session {
    Session() {
        if (!SteamAPI_Init()) throw std::runtime_error("Steamworks initialization failed");
    }
    ~Session() { SteamAPI_Shutdown(); }
};

template<class Result>
struct AsyncResult {
    Result result{};
    bool done = false;
    bool failed = false;
    CCallResult<AsyncResult<Result>, Result> callback;

    void receive(Result* value, bool io_failure) {
        result = *value;
        failed = io_failure;
        done = true;
    }
};

template<class Result, class Progress>
Result wait_for(SteamAPICall_t call, std::chrono::seconds timeout, Progress progress) {
    if (call == k_uAPICallInvalid) throw std::runtime_error("Steamworks rejected the call");
    AsyncResult<Result> response;
    response.callback.Set(call, &response, &AsyncResult<Result>::receive);
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!response.done && std::chrono::steady_clock::now() < deadline) {
        SteamAPI_RunCallbacks();
        if (!response.done) {
            progress();
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
        }
    }
    if (!response.done) throw std::runtime_error("Steamworks callback timed out");
    if (response.failed) throw std::runtime_error("Steamworks callback reported an I/O failure");
    return response.result;
}

std::string utf8(const std::wstring& value) {
    if (value.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
                                         static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    if (!size) throw std::runtime_error("invalid UTF-16 argument");
    std::string result(size, '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
                            static_cast<int>(value.size()), result.data(), size, nullptr, nullptr) != size) {
        throw std::runtime_error("could not encode argument as UTF-8");
    }
    return result;
}

std::string replace_newlines(std::string text) {
    for (std::size_t pos = 0; (pos = text.find("\r\n", pos)) != text.npos;) {
        text.erase(pos, 1);
        ++pos;
    }
    while (!text.empty() && text.back() == '\n') text.pop_back();
    return text;
}

std::string quote(const std::string& value) {
    const std::string hex = "0123456789abcdef";
    std::string result = "\"";
    for (const unsigned char ch : value) {
        if (ch == '\\' || ch == '"') result += '\\';
        if (ch < 32) {
            result += "\\u00";
            result += hex[ch >> 4];
            result += hex[ch & 15];
        } else {
            result += static_cast<char>(ch);
        }
    }
    return result + '"';
}

uint64 positive_id(const std::wstring& value) {
    if (value.empty() || value.front() == L'0' || value.find_first_not_of(L"0123456789") != value.npos)
        throw std::runtime_error("expected a positive Steam ID");
    return std::stoull(value);
}

void require(bool success, const char* diagnostic) {
    if (!success) throw std::runtime_error(diagnostic);
}

struct Query {
    ISteamUGC& ugc;
    UGCQueryHandle_t handle;
    ~Query() { ugc.ReleaseQueryUGCRequest(handle); }
};

struct Item {
    SteamUGCDetails_t details{};
    std::string metadata;
    std::string preview_url;
};

Item query(ISteamUGC& ugc, PublishedFileId_t id, const std::string& language) {
    const auto handle = ugc.CreateQueryUGCDetailsRequest(&id, 1);
    require(handle && handle != k_UGCQueryHandleInvalid, "Steamworks rejected the query handle");
    const Query request{ugc, handle};
    require(ugc.SetLanguage(handle, language.c_str()), "Steamworks rejected the query language");
    require(ugc.SetAllowCachedResponse(handle, 0), "Steamworks rejected the fresh query");
    require(ugc.SetReturnLongDescription(handle, true), "Steamworks rejected the full description query");
    require(ugc.SetReturnMetadata(handle, true), "Steamworks rejected the metadata query");
    const auto result = wait_for<SteamUGCQueryCompleted_t>(
        ugc.SendQueryUGCRequest(handle), std::chrono::seconds(30), [] {});
    require(result.m_eResult == k_EResultOK && result.m_handle == handle
            && result.m_unNumResultsReturned == 1 && result.m_unTotalMatchingResults == 1
            && !result.m_bCachedData, "Steamworks item query was incomplete");
    Item item;
    require(ugc.GetQueryUGCResult(handle, 0, &item.details)
            && item.details.m_eResult == k_EResultOK
            && item.details.m_nPublishedFileId == id, "Steamworks item details were unavailable");
    char metadata[k_cchDeveloperMetadataMax]{};
    // Items without developer metadata can legitimately return no value.
    if (ugc.GetQueryUGCMetadata(handle, 0, metadata, sizeof(metadata))) item.metadata = metadata;
    char preview[8192]{};
    if (ugc.GetQueryUGCPreviewURL(handle, 0, preview, sizeof(preview))) item.preview_url = preview;
    return item;
}

void require_owner(ISteamUser& user, const Item& item, uint64 owner) {
    require(user.BLoggedOn() && user.GetSteamID().ConvertToUint64() == owner,
            "the Steam client is not signed in as the specified owner");
    require(item.details.m_ulSteamIDOwner == owner && item.details.m_nCreatorAppID == app_id
            && item.details.m_nConsumerAppID == app_id && !item.details.m_bBanned
            && item.details.m_eVisibility == k_ERemoteStoragePublishedFileVisibilityPublic,
            "the Workshop item owner, app or status does not match");
}

std::string read_description(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    require(input.is_open(), "could not open the localized description");
    char buffer[k_cchPublishedDocumentDescriptionMax]{};
    input.read(buffer, sizeof(buffer));
    require(!input.bad() && input.gcount() > 0 && input.gcount() < sizeof(buffer),
            "the localized description is empty, oversized or unreadable");
    std::string description(buffer, static_cast<std::size_t>(input.gcount()));
    require(description.find('\0') == description.npos, "the localized description contains NUL");
    return description;
}

void print_query(const Item& item, uint64 owner, uint32 item_state) {
    const auto& details = item.details;
    std::cout << "{\"item_id\":" << details.m_nPublishedFileId
              << ",\"creator_app_id\":" << details.m_nCreatorAppID
              << ",\"consumer_app_id\":" << details.m_nConsumerAppID
              << ",\"owner_id\":\"" << details.m_ulSteamIDOwner << "\""
              << ",\"is_owner\":" << (details.m_ulSteamIDOwner == owner ? "true" : "false")
              << ",\"banned\":" << (details.m_bBanned ? "true" : "false")
              << ",\"visibility\":" << details.m_eVisibility
              << ",\"item_state\":" << item_state
              << ",\"content_handle\":" << details.m_hFile
              << ",\"preview_handle\":" << details.m_hPreviewFile
              << ",\"preview_url\":" << quote(item.preview_url)
              << ",\"title\":" << quote(details.m_rgchTitle)
              << ",\"description\":" << quote(details.m_rgchDescription)
              << ",\"developer_metadata\":" << quote(item.metadata) << "}\n";
}

void update(ISteamUGC& ugc, ISteamUser& user, PublishedFileId_t id, uint64 owner,
            const std::string& language, wchar_t** args, bool with_assets, bool& submitted) {
    const auto description = read_description(std::filesystem::path(args[5]));
    const auto baseline = replace_newlines(utf8(args[6]));
    const auto previous = query(ugc, id, language);
    require_owner(user, previous, owner);
    require(replace_newlines(previous.details.m_rgchDescription) == baseline,
            "the localized Workshop description changed before submit");
    const auto handle = ugc.StartItemUpdate(app_id, id);
    require(handle && handle != k_UGCUpdateHandleInvalid, "Steamworks rejected the update handle");
    require(ugc.SetItemUpdateLanguage(handle, language.c_str()), "Steamworks rejected update language");
    require(ugc.SetItemDescription(handle, description.c_str()), "Steamworks rejected description");
    std::string note;
    if (with_assets) {
        const auto content = utf8(args[7]);
        const auto preview = utf8(args[8]);
        const auto metadata = utf8(args[9]);
        require(previous.details.m_hPreviewFile == std::stoull(args[11])
                && previous.details.m_hFile == std::stoull(args[12])
                && previous.metadata == utf8(args[13]),
                "the Workshop assets changed before submit");
        require(ugc.SetItemContent(handle, content.c_str()), "Steamworks rejected content directory");
        require(ugc.SetItemPreview(handle, preview.c_str()), "Steamworks rejected preview file");
        require(ugc.SetItemMetadata(handle, metadata.c_str()), "Steamworks rejected package marker");
        note = utf8(args[10]);
    }
    require_owner(user, previous, owner);
    const auto call = ugc.SubmitItemUpdate(handle, note.c_str());
    require(call != k_uAPICallInvalid, "Steamworks rejected the update handle synchronously");
    submitted = true;
    const auto result = wait_for<SubmitItemUpdateResult_t>(call,
        std::chrono::seconds(180), [&] {
            uint64 processed = 0, total = 0;
            ugc.GetItemUpdateProgress(handle, &processed, &total);
        });
    std::cout << "{\"item_id\":" << result.m_nPublishedFileId
              << ",\"result_code\":" << result.m_eResult
              << ",\"needs_legal_agreement\":"
              << (result.m_bUserNeedsToAcceptWorkshopLegalAgreement ? "true" : "false") << "}\n";
}

std::string install_path(ISteamUGC& ugc, PublishedFileId_t id) {
    const auto state = ugc.GetItemState(id);
    if (!(state & k_EItemStateInstalled) || !(state & k_EItemStateSubscribed)
        || state & (k_EItemStateLegacyItem | k_EItemStateNeedsUpdate |
                    k_EItemStateDownloading | k_EItemStateDownloadPending)) {
        return {};
    }
    uint64 bytes = 0;
    uint32 installed_at = 0;
    char path[32768]{};
    if (!ugc.GetItemInstallInfo(id, &bytes, path, sizeof(path), &installed_at)) return {};
    return path;
}

} // namespace

int wmain(int argc, wchar_t** argv) {
    const std::wstring command = argc > 1 ? argv[1] : L"";
    bool submitted = false;
    try {
        if (argc == 2 && command == L"version") {
            std::cout << "{\"protocol\":2}\n";
            return 0;
        }
        const bool query_only = argc == 5 && command == L"query";
        const bool submit = (argc == 7 || argc == 14) && command == L"update";
        const bool installed = argc == 4 && command == L"installed";
        require(query_only || submit || installed, "invalid helper command or argument count");
        const auto id = positive_id(argv[2]);
        const auto owner = positive_id(argv[3]);
        const auto language = installed ? "english" : utf8(argv[4]);
        const Session session;
        auto* user = SteamUser();
        auto* utils = SteamUtils();
        auto* ugc = SteamUGC();
        require(user && utils && ugc && utils->GetAppID() == app_id,
                "required Victoria 3 Steamworks interfaces are unavailable");
        require(user->BLoggedOn() && user->GetSteamID().ConvertToUint64() == owner,
                "the Steam client is not signed in as the specified owner");
        if (query_only) {
            const auto item = query(*ugc, id, language);
            require_owner(*user, item, owner);
            print_query(item, owner, ugc->GetItemState(id));
        } else if (submit) {
            update(*ugc, *user, id, owner, language, argv, argc == 14, submitted);
        } else {
            const auto item = query(*ugc, id, language);
            require_owner(*user, item, owner);
            std::cout << "{\"install_path\":" << quote(install_path(*ugc, id)) << "}\n";
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return command == L"update" && !submitted ? 3 : 2;
    }
}
