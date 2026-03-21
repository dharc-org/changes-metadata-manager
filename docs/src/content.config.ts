// SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelomas@gmail.com>
//
// SPDX-License-Identifier: ISC

import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
	docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
