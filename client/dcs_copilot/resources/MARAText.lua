-- MARA text overlay hook. Receives bounded assistant text on loopback and asks
-- DCS's mission scripting environment to show its standard top-right message.
local socket_ok, socket = pcall(require, "socket")
if not socket_ok then return end

local HOST = "127.0.0.1"
local PORT = 7782
local PROTOCOL = "MARA_TEXT/1"
local MAX_TEXT_BYTES = 4096
local input = nil

local function ensure_socket()
    if input then return true end
    local candidate = socket.udp()
    if not candidate then return false end
    candidate:settimeout(0)
    local ok = candidate:setsockname(HOST, PORT)
    if not ok then
        candidate:close()
        return false
    end
    input = candidate
    return true
end

local function show_text(text)
    local duration = math.max(8, math.min(30, math.ceil(#text / 15)))
    local mission_code = string.format(
        "trigger.action.outText(%q, %d, true)", text, duration
    )
    -- a_do_script enters the real mission environment where trigger.action is
    -- available. Both nested strings use %q so received text cannot become code.
    local ok = pcall(
        net.dostring_in,
        "mission",
        string.format("a_do_script(%q)", mission_code)
    )
    return ok
end

local function poll_text()
    if not ensure_socket() then return end
    while true do
        local datagram, peer_host = input:receivefrom()
        if not datagram then return end
        if peer_host == HOST and #datagram <= MAX_TEXT_BYTES + 64 then
            local header, payload = datagram:match("^([^\n]+)\n(.*)$")
            if header and payload then
                local protocol, length_text = header:match("^(%S+)%s+(%d+)$")
                local length = tonumber(length_text)
                if protocol == PROTOCOL and length and length <= MAX_TEXT_BYTES
                    and #payload == length then
                    pcall(show_text, payload)
                end
            end
        end
    end
end

local callbacks = {}

function callbacks.onSimulationFrame()
    poll_text()
end

function callbacks.onSimulationStop()
    if input then input:close() end
    input = nil
end

DCS.setUserCallbacks(callbacks)
