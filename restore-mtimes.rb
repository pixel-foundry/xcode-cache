#!/usr/bin/env ruby
# frozen_string_literal: true

require 'digest'
require 'json'

derived_data_path = ENV.fetch('DERIVED_DATA_PATH')
metadata_path = File.join(derived_data_path, 'xcode-cache-mtime.json')

unless File.file?(metadata_path)
	puts "No source mtime metadata found at #{metadata_path}."
	exit 0
end

def digest_for(path)
	if File.directory?(path)
		Digest::SHA256.hexdigest(Dir.children(path).sort.join)
	else
		Digest::SHA256.file(path).hexdigest
	end
end

restored = 0
JSON.parse(File.read(metadata_path)).each do |entry|
	path = entry.fetch('path')
	next unless File.exist?(path)
	next unless digest_for(path) == entry.fetch('sha256')

	seconds, nanoseconds = entry.fetch('time').split('.', 2).map(&:to_i)
	time = Time.at(seconds, nanoseconds, :nanosecond)
	File.utime(time, time, path)
	restored += 1
end

puts "Restored #{restored} source mtimes."
