-- MARA normalized spatial export. World objects are read only when DCS permits it.
local socket_ok, socket = pcall(require, "socket")
if not socket_ok then return end

local HOST = "127.0.0.1"
local PORT = 7780
-- Selected normalized Coach targets are intentionally published at 5 Hz, not
-- as a raw 10-30 Hz world stream.
local INTERVAL = 0.2
local RAD_TO_DEG = 57.29577951308232
local MPS_TO_KT = 1.9438444924406
local M_TO_FT = 3.2808398950131
local MPS_TO_FPM = 196.85039370079
local sequence = 0
local next_send = 0
local output = nil

local function finite(value)
    return type(value) == "number" and value == value
        and value ~= math.huge and value ~= -math.huge
end

local function boolean_permission(name, fallback)
    local fn = _G[name]
    if type(fn) ~= "function" then return fallback end
    local ok, value = pcall(fn)
    return ok and value == true
end

local function escape(value)
    value = tostring(value or ""):sub(1, 128)
    value = value:gsub("\\", "\\\\"):gsub('"', '\\"')
    value = value:gsub("\b", "\\b"):gsub("\f", "\\f")
    value = value:gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
    return '"' .. value .. '"'
end

local function number(value)
    if not finite(value) then return "null" end
    return string.format("%.9g", value)
end

local function bool(value)
    return value and "true" or "false"
end

local function vec3(value)
    if type(value) ~= "table" or not finite(value.x)
        or not finite(value.y) or not finite(value.z) then return nil end
    return '{"x":' .. number(value.x) .. ',"y":' .. number(value.y)
        .. ',"z":' .. number(value.z) .. '}'
end

local function optional_field(name, value, encoder)
    if value == nil then return "" end
    return ',' .. escape(name) .. ':' .. encoder(value)
end

local function object_position(object)
    if type(object) ~= "table" then return nil end
    return object.Position or object.position
end

local function type_level(object, key)
    local object_type = object and (object.Type or object.type)
    if type(object_type) ~= "table" then return nil end
    return object_type[key] or object_type[key:lower()]
end

local function object_name(object)
    if type(object) ~= "table" then return "" end
    return tostring(object.Name or object.name or object.UnitName or object.unitName or "")
end

local function is_carrier(object)
    local name = object_name(object):upper()
    return type_level(object, "level1") == 3 and (
        name:find("CVN", 1, true) or name:find("STENNIS", 1, true)
        or name:find("FORRESTAL", 1, true) or name:find("KUZNE", 1, true)
        or name:find("CARRIER", 1, true)
    )
end

local function is_aircraft(object)
    return type_level(object, "level1") == 1
end

local function distance_squared(first, second)
    if not first or not second then return math.huge end
    local x, y, z = first.x - second.x, first.y - second.y, first.z - second.z
    return x * x + y * y + z * z
end

local function selected_references(self_data, allowed)
    if not allowed or not self_data or not object_position(self_data) then return {} end
    local ok, objects = pcall(LoGetWorldObjects)
    if not ok or type(objects) ~= "table" then return {} end
    local own_position = object_position(self_data)
    local own_name = object_name(self_data)
    local own_coalition = self_data.Coalition or self_data.coalition
    if own_coalition == nil then
        for _, object in pairs(objects) do
            local same_name = own_name ~= "" and object_name(object) == own_name
            local same_position = distance_squared(
                own_position, object_position(object)
            ) < 4
            if same_name or same_position then
                own_coalition = object.Coalition or object.coalition
                if own_coalition ~= nil then break end
            end
        end
    end
    local lead, lead_distance = nil, math.huge
    local carrier, carrier_distance = nil, math.huge
    for object_id, object in pairs(objects) do
        local position = object_position(object)
        local distance = distance_squared(own_position, position)
        if position and distance > 100 and object_name(object) ~= own_name then
            local object_coalition = object.Coalition or object.coalition
            local friendly = own_coalition ~= nil and object_coalition ~= nil
                and own_coalition == object_coalition
            if friendly and is_aircraft(object) and distance < lead_distance
                and distance < 25000000 then
                lead = { id = tostring(object_id), data = object }
                lead_distance = distance
            elseif friendly and is_carrier(object) and distance < carrier_distance then
                carrier = { id = tostring(object_id), data = object }
                carrier_distance = distance
            end
        end
    end
    local result = {}
    if lead then result[#result + 1] = { kind = "LEAD_AIRCRAFT", selected = lead } end
    if carrier then result[#result + 1] = { kind = "CARRIER", selected = carrier } end
    return result
end

local function encode_reference(reference)
    local object = reference.selected.data
    local position = vec3(object_position(object))
    if not position then return nil end
    local heading = object.Heading or object.heading or 0
    local encoded = '{"object_id":' .. escape(reference.selected.id)
        .. ',"object_type":' .. escape(reference.kind)
        .. ',"position":' .. position
        .. ',"heading_deg":' .. number(heading * RAD_TO_DEG)
    local velocity = vec3(object.Velocity or object.velocity)
    if velocity then encoded = encoded .. ',"velocity":' .. velocity end
    if finite(object.Pitch or object.pitch) then
        encoded = encoded .. ',"pitch_deg":' .. number((object.Pitch or object.pitch) * RAD_TO_DEG)
    end
    if finite(object.Bank or object.bank) then
        encoded = encoded .. ',"roll_deg":' .. number((object.Bank or object.bank) * RAD_TO_DEG)
    end
    local name = object_name(object)
    if name ~= "" then encoded = encoded .. ',"name":' .. escape(name) end
    return encoded .. '}'
end

local function encode_ownship(self_data)
    if not self_data then return "null" end
    local position = vec3(object_position(self_data))
    if not position then return "null" end
    local velocity = nil
    if type(LoGetVectorVelocity) == "function" then
        local ok, value = pcall(LoGetVectorVelocity)
        if ok then velocity = vec3(value) end
    end
    local encoded = '{"position":' .. position
    if velocity then encoded = encoded .. ',"velocity":' .. velocity end
    if finite(self_data.Heading) then
        encoded = encoded .. ',"heading_deg":' .. number(self_data.Heading * RAD_TO_DEG)
    end
    if finite(self_data.Pitch) then
        encoded = encoded .. ',"pitch_deg":' .. number(self_data.Pitch * RAD_TO_DEG)
    end
    if finite(self_data.Bank) then
        encoded = encoded .. ',"roll_deg":' .. number(self_data.Bank * RAD_TO_DEG)
    end
    encoded = encoded .. ',"altitude_msl_ft":' .. number(object_position(self_data).y * M_TO_FT)
    if type(LoGetAltitudeAboveGroundLevel) == "function" then
        local ok, value = pcall(LoGetAltitudeAboveGroundLevel)
        if ok and finite(value) then encoded = encoded .. ',"altitude_agl_ft":' .. number(value * M_TO_FT) end
    end
    if type(LoGetIndicatedAirSpeed) == "function" then
        local ok, value = pcall(LoGetIndicatedAirSpeed)
        if ok and finite(value) then encoded = encoded .. ',"indicated_airspeed_kt":' .. number(value * MPS_TO_KT) end
    end
    if type(LoGetAngleOfAttack) == "function" then
        local ok, value = pcall(LoGetAngleOfAttack)
        if ok and finite(value) then encoded = encoded .. ',"aoa_deg":' .. number(value * RAD_TO_DEG) end
    end
    if type(LoGetAccelerationUnits) == "function" then
        local ok, value = pcall(LoGetAccelerationUnits)
        if ok and type(value) == "table" and finite(value.y) then encoded = encoded .. ',"g_force":' .. number(value.y) end
    end
    if type(LoGetVectorVelocity) == "function" then
        local ok, value = pcall(LoGetVectorVelocity)
        if ok and type(value) == "table" and finite(value.y) then encoded = encoded .. ',"vertical_speed_fpm":' .. number(value.y * MPS_TO_FPM) end
    end
    return encoded .. '}'
end

local function ensure_socket()
    if output then return true end
    local candidate = socket.udp()
    if not candidate then return false end
    candidate:settimeout(0)
    output = candidate
    return true
end

local function send_observation()
    if not ensure_socket() then return end
    local ownship_allowed = boolean_permission("LoIsOwnshipExportAllowed", true)
    local world_allowed = boolean_permission("LoIsObjectExportAllowed", false)
    local sensor_allowed = boolean_permission("LoIsSensorExportAllowed", false)
    local self_data = nil
    if ownship_allowed and type(LoGetSelfData) == "function" then
        local ok, value = pcall(LoGetSelfData)
        if ok then self_data = value end
    end
    local references = selected_references(self_data, world_allowed)
    local encoded_references = {}
    for _, reference in ipairs(references) do
        local encoded = encode_reference(reference)
        if encoded then encoded_references[#encoded_references + 1] = encoded end
    end
    sequence = sequence + 1
    local payload = '{"coach_telemetry_version":1,"sequence":' .. sequence
        .. ',"observed_at_ms":' .. math.floor(socket.gettime() * 1000)
        .. ',"capabilities":{"ownship_export":' .. bool(ownship_allowed)
        .. ',"world_object_export":' .. bool(world_allowed)
        .. ',"sensor_export":' .. bool(sensor_allowed)
        .. ',"cockpit_state":false}'
        .. ',"ownship":' .. (ownship_allowed and encode_ownship(self_data) or "null")
        .. ',"references":[' .. table.concat(encoded_references, ",") .. ']}'
    output:sendto(payload, HOST, PORT)
end

local previous_start = LuaExportStart
LuaExportStart = function()
    if previous_start then previous_start() end
    ensure_socket()
end

local previous_after = LuaExportAfterNextFrame
LuaExportAfterNextFrame = function()
    if previous_after then previous_after() end
    local now = socket.gettime()
    if now >= next_send then
        next_send = now + INTERVAL
        local ok = pcall(send_observation)
        if not ok then -- Keep the export chain alive; try again next frame.
            if output then output:close() end
            output = nil
        end
    end
end

local previous_stop = LuaExportStop
LuaExportStop = function()
    if previous_stop then previous_stop() end
    if output then output:close() end
    output = nil
end
