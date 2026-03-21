// SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelomas@gmail.com>
//
// SPDX-License-Identifier: ISC

import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import rehypeExternalLinks from 'rehype-external-links';

export default defineConfig({
	site: 'https://dharc-org.github.io',
	base: '/changes-metadata-manager',
	markdown: {
		rehypePlugins: [
			[rehypeExternalLinks, { target: '_blank', rel: ['noopener', 'noreferrer'] }],
		],
	},
	integrations: [
		starlight({
			title: 'CHANGES Metadata Manager',
			description: 'Metadata and provenance generator for digitized cultural heritage objects in the CHANGES project',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/dharc-org/changes-metadata-manager' },
			],
			sidebar: [
				{
					label: 'Guides',
					items: [
						{ label: 'Getting started', slug: 'getting_started' },
						{ label: 'Folder metadata builder', slug: 'guides/folder_metadata' },
						{ label: 'Zenodo upload', slug: 'guides/zenodo_upload' },
						{ label: 'SharePoint sync', slug: 'guides/sharepoint_sync' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'Architecture', slug: 'reference/architecture' },
						{ label: 'Digitization stages', slug: 'reference/stages' },
						{ label: 'Naming convention', slug: 'reference/naming_convention' },
					],
				},
			],
		}),
	],
});
