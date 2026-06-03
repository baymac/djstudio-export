// Apple Music bridge for playlist-syncer CLI.
// Outputs NDJSON to stdout — one JSON object per line.
// Each record: catalog_id, library_id, name, artist, album, genre, loved, playlists
//
// Modes (mutually exclusive, checked in order):
//   --check                  → test authorization; exit 0 = OK, exit 2 = not authorized
//   --list-playlists         → JSON array of user playlist names (excludes "Favourite Songs")
//   --all-playlists          → NDJSON, one row per playlist ENTRY (ordered, dup-preserving,
//                              tagged with native_playlist_id + position) — faithful capture
//   --library-songs          → NDJSON for songs with libraryAddedDate set (Music app "Songs" tab)
//   --favorites              → NDJSON for songs in the "Favourite Songs" playlist

import MusicKit
import Foundation

// ---------- Helpers ----------

func extractCatalogID(from playParameters: PlayParameters?) -> String {
    guard let pp = playParameters,
          let data = try? JSONEncoder().encode(pp),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else { return "" }
    if let nested = json["catalogID"] as? [String: Any], let value = nested["value"] {
        return "\(value)"
    }
    if let flat = json["catalogId"] { return "\(flat)" }
    return ""
}

func toJSON(_ dict: [String: Any]) -> String {
    let data = try! JSONSerialization.data(withJSONObject: dict)
    return String(data: data, encoding: .utf8)!
}

typealias TrackKey = String  // "title|||artist"

func trackKey(title: String, artist: String) -> TrackKey {
    "\(title.lowercased())|||\(artist.lowercased())"
}

func keyFromTrack(_ track: Track) -> TrackKey? {
    switch track {
    case .song(let s): return trackKey(title: s.title, artist: s.artistName)
    default: return nil
    }
}

// ---------- Auth check ----------

func runCheck() async {
    let status = await MusicAuthorization.request()
    if status == .authorized {
        exit(0)
    } else {
        fputs("MusicKit not authorized (status: \(status))\n", stderr)
        fputs("Open the Music app and re-run this command to grant access.\n", stderr)
        exit(2)
    }
}

// ---------- List playlists ----------

func runListPlaylists() async {
    let status = await MusicAuthorization.request()
    guard status == .authorized else {
        fputs("Error: MusicKit not authorized\n", stderr)
        exit(2)
    }

    let request = MusicLibraryRequest<Playlist>()
    guard let response = try? await request.response() else {
        fputs("Error: could not fetch playlists\n", stderr)
        exit(1)
    }

    // "Favourite Songs" is accessed via --favorites flag, not as a regular playlist
    let names = response.items.map { $0.name }.filter { $0 != "Favourite Songs" }
    let data = try! JSONSerialization.data(withJSONObject: names)
    print(String(data: data, encoding: .utf8)!)
    exit(0)
}

// ---------- Playlist data loading ----------

// Fast path: only load the Favourite Songs playlist keys (used for --favorites).
func loadFavouriteKeys() async -> Set<TrackKey> {
    var keys = Set<TrackKey>()
    let req = MusicLibraryRequest<Playlist>()
    guard let response = try? await req.response() else { return keys }
    for playlist in response.items {
        guard playlist.name == "Favourite Songs",
              let detailed = try? await playlist.with([.tracks]),
              let tracks = detailed.tracks else { continue }
        for track in tracks {
            if let key = keyFromTrack(track) { keys.insert(key) }
        }
        break
    }
    return keys
}

struct PlaylistData {
    var favouriteKeys: Set<TrackKey> = []
}

// ---------- Stream library songs ----------

enum StreamMode {
    case library          // only songs with libraryAddedDate set (Music app "Songs" tab)
    case favorites        // only songs present in favouriteKeys
}

func streamSongs(filter: PlaylistData, mode: StreamMode) async {
    let iso8601 = ISO8601DateFormatter()
    var offset = 0
    let limit = 100
    var total = 0

    while true {
        var request = MusicLibraryRequest<Song>()
        request.limit = limit
        request.offset = offset

        guard let response = try? await request.response() else {
            fputs("Error fetching at offset \(offset)\n", stderr)
            break
        }

        for song in response.items {
            let key = trackKey(title: song.title, artist: song.artistName)

            let include: Bool
            switch mode {
            case .library:
                include = song.libraryAddedDate != nil
            case .favorites:
                include = filter.favouriteKeys.contains(key)
            }

            guard include else { continue }

            let catalogID = extractCatalogID(from: song.playParameters)
            let addedDateStr = song.libraryAddedDate.map { iso8601.string(from: $0) } ?? ""
            let record: [String: Any] = [
                "catalog_id": catalogID,
                "library_id": song.id.rawValue,
                "name": song.title,
                "artist": song.artistName,
                "album": song.albumTitle ?? "",
                "genre": song.genreNames.first ?? "",
                "loved": filter.favouriteKeys.contains(key),
                "playlists": [String](),
                "library_added_date": addedDateStr,
            ]
            print(toJSON(record))
            total += 1
        }
        fflush(stdout)

        if response.items.count < limit { break }
        offset += limit
        if offset % 500 == 0 {
            fputs("Fetched \(total)…\n", stderr)
        }
    }

    fputs("Done: \(total) songs\n", stderr)
}

// ---------- Stream all playlists (faithful capture) ----------

// Emits one NDJSON row per playlist ENTRY, in playlist order. Unlike the
// key-based no-args mode this preserves position and keeps duplicate entries,
// and tags each row with the playlist's STABLE id — what `dj sync music` needs
// to faithfully back up (and later recreate) a playlist.
func streamAllPlaylists() async {
    let request = MusicLibraryRequest<Playlist>()
    guard let response = try? await request.response() else {
        fputs("Error: could not fetch playlists\n", stderr)
        exit(1)
    }

    var total = 0
    for playlist in response.items {
        // "Favourite Songs" is captured authoritatively via --favorites (the
        // __favorites__ pseudo-playlist); skip it here so it isn't ALSO stored
        // under its real playlist id as a duplicate. Same exclusion as --list-playlists.
        if playlist.name == "Favourite Songs" { continue }
        guard let detailed = try? await playlist.with([.tracks]),
              let tracks = detailed.tracks else { continue }

        for (idx, track) in tracks.enumerated() {
            guard case .song(let song) = track else { continue }
            let catalogID = extractCatalogID(from: song.playParameters)
            let record: [String: Any] = [
                "playlist_name": playlist.name,
                "native_playlist_id": playlist.id.rawValue,
                "position": idx,
                "native_track_id": catalogID.isEmpty ? song.id.rawValue : catalogID,
                "library_id": song.id.rawValue,
                "url": song.url?.absoluteString ?? "",
                "name": song.title,
                "artist": song.artistName,
                "album": song.albumTitle ?? "",
            ]
            print(toJSON(record))
            total += 1
        }
        fflush(stdout)
    }
    fputs("Done: \(total) playlist entries\n", stderr)
}

// ---------- Entry point ----------

func main() async {
    let args = CommandLine.arguments.dropFirst()

    if args.contains("--check") {
        await runCheck()
        return
    }

    if args.contains("--list-playlists") {
        await runListPlaylists()
        return
    }

    let status = await MusicAuthorization.request()
    guard status == .authorized else {
        fputs("Error: MusicKit not authorized\n", stderr)
        exit(2)
    }

    if args.contains("--all-playlists") {
        fputs("Streaming all playlists (faithful, ordered)…\n", stderr)
        await streamAllPlaylists()
        exit(0)
    }

    if args.contains("--library-songs") {
        fputs("Streaming library songs (libraryAddedDate set)…\n", stderr)
        await streamSongs(filter: PlaylistData(), mode: .library)
        exit(0)
    }

    if args.contains("--favorites") {
        fputs("Loading Favourite Songs playlist…\n", stderr)
        let favKeys = await loadFavouriteKeys()
        fputs("Streaming \(favKeys.count) favourite songs…\n", stderr)
        var filter = PlaylistData()
        filter.favouriteKeys = favKeys
        await streamSongs(filter: filter, mode: .favorites)
        exit(0)
    }

    fputs("Error: no mode specified. Use one of: --check, --list-playlists, "
          + "--all-playlists, --library-songs, --favorites.\n", stderr)
    exit(2)
}

Task { await main() }
RunLoop.main.run(until: Date(timeIntervalSinceNow: 600))
