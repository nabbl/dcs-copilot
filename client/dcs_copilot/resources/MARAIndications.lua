-- Development-only, loopback list_indication() probe for MARA.
-- This file does not inspect world objects and is idle unless a local tool asks.

local socket_available, socket = pcall(require, "socket")
if not socket_available then return end
local CONTROL_HOST = "127.0.0.1"
local CONTROL_PORT = 7779
local PROTOCOL = "MARA_INDICATION/1"
local MAX_CHUNK_BYTES = 60000
local MAX_INDICATOR_ID = 255
local MAX_RANGE_SIZE = 64
local MAX_WATCHES = 8

local mara_socket = nil
local watches = {}
local sequence = 0
local last_socket_attempt = 0

local function ensure_socket()
    if mara_socket then return true end
    local now = socket.gettime()
    if now - last_socket_attempt < 5 then return false end
    last_socket_attempt = now
    local candidate = socket.udp()
    candidate:settimeout(0)
    local ok = candidate:setsockname(CONTROL_HOST, CONTROL_PORT)
    if not ok then
        candidate:close()
        return false
    end
    mara_socket = candidate
    return true
end

local function valid_token(token)
    return token and #token >= 8 and #token <= 64 and token:match("^[0-9a-fA-F]+$")
end

local function valid_range(first_id, last_id)
    return first_id and last_id and first_id >= 0 and last_id >= first_id
        and last_id <= MAX_INDICATOR_ID and last_id - first_id + 1 <= MAX_RANGE_SIZE
end

local function read_indicator(indicator_id)
    local ok, value = pcall(list_indication, indicator_id)
    if not ok then return "ERROR", tostring(value) end
    if value == nil then return "OK", "" end
    return "OK", tostring(value)
end

local function send_indicator(peer_host, peer_port, token, indicator_id, status, raw)
    if not mara_socket then return end
    sequence = sequence + 1
    local observed_at = socket.gettime()
    local length = #raw
    local chunk_count = math.max(1, math.ceil(length / MAX_CHUNK_BYTES))
    for chunk_index = 0, chunk_count - 1 do
        local first = chunk_index * MAX_CHUNK_BYTES + 1
        local payload = string.sub(raw, first, first + MAX_CHUNK_BYTES - 1)
        local header = string.format(
            "MARA_INDICATION 1 %s %d %d %d %d %.6f %s %d\n",
            token, sequence, indicator_id, chunk_index, chunk_count,
            observed_at, status, #payload
        )
        mara_socket:sendto(header .. payload, peer_host, peer_port)
    end
end

local function scan(peer_host, peer_port, token, first_id, last_id)
    for indicator_id = first_id, last_id do
        local status, raw = read_indicator(indicator_id)
        send_indicator(peer_host, peer_port, token, indicator_id, status, raw)
    end
end

local function handle_command(command, peer_host, peer_port)
    local protocol, action, token, first_text, last_text, interval_text =
        command:match("^(%S+)%s+(%S+)%s+(%S+)%s*(%S*)%s*(%S*)%s*(%S*)$")
    if protocol ~= PROTOCOL or not valid_token(token) then return end
    if action == "STOP" then
        watches[token] = nil
        return
    end
    local first_id = tonumber(first_text)
    local last_id = tonumber(last_text)
    if not valid_range(first_id, last_id) then return end
    if action == "SCAN" then
        scan(peer_host, peer_port, token, first_id, last_id)
        return
    end
    if action ~= "WATCH" then return end
    local interval = tonumber(interval_text)
    if not interval or interval < 0.1 or interval > 10 then return end
    local existing = watches[token]
    if existing and existing.first_id == first_id and existing.last_id == last_id then
        existing.peer_host = peer_host
        existing.peer_port = peer_port
        existing.interval = interval
        existing.last_heartbeat = socket.gettime()
        return
    end
    local watch_count = 0
    for _ in pairs(watches) do watch_count = watch_count + 1 end
    if not existing and watch_count >= MAX_WATCHES then return end
    watches[token] = {
        peer_host = peer_host,
        peer_port = peer_port,
        first_id = first_id,
        last_id = last_id,
        interval = interval,
        next_poll = 0,
        last_heartbeat = socket.gettime(),
        previous = {},
    }
end

local function poll_commands()
    if not ensure_socket() then return end
    while true do
        local command, peer_host, peer_port = mara_socket:receivefrom()
        if not command then return end
        handle_command(command, peer_host, peer_port)
    end
end

local function poll_watches()
    local now = socket.gettime()
    for token, watch in pairs(watches) do
        if now - watch.last_heartbeat > 5 then
            watches[token] = nil
        elseif now >= watch.next_poll then
            watch.next_poll = now + watch.interval
            for indicator_id = watch.first_id, watch.last_id do
                local status, raw = read_indicator(indicator_id)
                local fingerprint = status .. "\n" .. raw
                if watch.previous[indicator_id] ~= fingerprint then
                    watch.previous[indicator_id] = fingerprint
                    send_indicator(
                        watch.peer_host, watch.peer_port, token,
                        indicator_id, status, raw
                    )
                end
            end
        end
    end
end

local previous_start = LuaExportStart
LuaExportStart = function()
    if previous_start then previous_start() end
    ensure_socket()
end

local previous_after_next_frame = LuaExportAfterNextFrame
LuaExportAfterNextFrame = function()
    if previous_after_next_frame then previous_after_next_frame() end
    poll_commands()
    poll_watches()
end

local previous_stop = LuaExportStop
LuaExportStop = function()
    if previous_stop then previous_stop() end
    watches = {}
    if mara_socket then
        mara_socket:close()
        mara_socket = nil
    end
end
