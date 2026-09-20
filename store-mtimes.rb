#!/usr/bin/env ruby
# frozen_string_literal: true

require 'digest'
require 'json'
require 'pathname'

derived_data_path = File.expand_path(ENV.fetch('DERIVED_DATA_PATH'))
source_packages_path = File.expand_path(ENV.fetch('SOURCE_PACKAGES_PATH'))
workspace = File.expand_path(ENV.fetch('GITHUB_WORKSPACE', Dir.pwd))

unless File.directory?(derived_data_path)
	warn "DerivedData does not exist at #{derived_data_path}; skipping mtime metadata."
	exit 0
end

default_patterns = %w[
	**/*.swift **/*.xib **/*.storyboard **/*.strings **/*.xcstrings **/*.plist
	**/*.intentdefinition **/*.json **/*.xcassets **/*.xcassets/**/* **/*.bundle
	**/*.bundle/**/* **/*.xcdatamodel **/*.xcdatamodel/**/* **/*.framework
	**/*.framework/**/* **/*.xcframework **/*.xcframework/**/* **/*.m **/*.mm
	**/*.h **/*.c **/*.cc **/*.cpp **/*.hpp **/*.hxx
]
custom_patterns = ENV.fetch('MTIME_TARGETS', '').lines.map(&:strip).reject(&:empty?)
excluded_prefixes = [derived_data_path, source_packages_path]

def digest_for(path)
	if File.directory?(path)
		Digest::SHA256.hexdigest(Dir.children(path).sort.join)
	else
		Digest::SHA256.file(path).hexdigest
	end
end

paths = Dir.chdir(workspace) do
	(default_patterns + custom_patterns).flat_map { |pattern| Dir.glob(pattern, File::FNM_EXTGLOB) }
		.uniq
		.select { |path| File.exist?(path) }
		.reject do |path|
			excluded_prefixes.any? do |prefix|
				absolute_path = File.expand_path(path, workspace)
				absolute_path == prefix || absolute_path.start_with?("#{prefix}/")
			end
		end
		.sort
end

metadata = paths.map do |path|
	absolute_path = File.expand_path(path, workspace)
	mtime = File.stat(absolute_path).mtime
	{
		path: Pathname.new(absolute_path).relative_path_from(Pathname.new(workspace)).to_s,
		time: format('%d.%09d', mtime.to_i, mtime.nsec),
		sha256: digest_for(absolute_path),
	}
end

File.write(File.join(derived_data_path, 'xcode-cache-mtime.json'), JSON.generate(metadata))
puts "Stored #{metadata.count} source mtimes."
