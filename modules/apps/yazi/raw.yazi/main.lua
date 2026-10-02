-- Camera RAW formats aren't decodable by Yazi's built-in image previewer, but
-- they carry an embedded JPEG (under one of a few possible EXIF tags
-- depending on manufacturer) that exiftool can pull out and hand off to the
-- normal image-preview path.
local TAGS = { "-PreviewImage", "-JpgFromRaw", "-ThumbnailImage" }

local M = {}

function M:peek(job)
	local start, cache = os.clock(), ya.file_cache(job)
	if not cache then
		return
	end

	local ok, err = self:preload(job)
	if not ok or err then
		return ya.preview_widget(job, err)
	end

	ya.sleep(math.max(0, rt.preview.image_delay / 1000 + start - os.clock()))

	local _, err = ya.image_show(cache, job.area)
	ya.preview_widget(job, err)
end

function M:seek() end

function M:preload(job)
	local cache = ya.file_cache(job)
	if not cache then
		return true
	elseif fs.cha(cache, false) then
		return true
	end

	for _, tag in ipairs(TAGS) do
		-- The trailing `[ -s "$3" ]` folds the non-empty-output check into
		-- the command's exit status, so success here already means a real
		-- preview was extracted -- no need to separately stat the result.
		local status = Command("sh")
			:arg({
				"-c",
				'exiftool -b "$1" "$2" > "$3" 2>/dev/null && [ -s "$3" ]',
				"sh",
				tag,
				tostring(job.file.path),
				tostring(cache),
			})
			:status()

		if status and status.success then
			return true
		end
	end

	return false, Err("No embedded preview found in %s", tostring(job.file.url))
end

return M
