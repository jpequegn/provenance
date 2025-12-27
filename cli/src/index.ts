#!/usr/bin/env node
import { Command } from 'commander';

const program = new Command();

program
  .name('provo')
  .description('Capture the why behind your decisions')
  .version('0.1.0');

// Quick capture command (default)
program
  .argument('[message]', 'Quick capture a thought or decision')
  .option('-p, --project <project>', 'Associate with a project')
  .option('-t, --topic <topic>', 'Add a topic tag')
  .option('--link <url>', 'Link to an external reference')
  .action(async (message, options) => {
    if (message) {
      // TODO: Implement capture via API
      console.log(`Capturing: "${message}"`);
      if (options.project) console.log(`  Project: ${options.project}`);
      if (options.topic) console.log(`  Topic: ${options.topic}`);
      if (options.link) console.log(`  Link: ${options.link}`);
      console.log('\n[Not yet implemented - API integration pending]');
    } else {
      program.help();
    }
  });

// Search command
program
  .command('search <query>')
  .description('Search your context fragments')
  .option('-n, --limit <number>', 'Number of results', '5')
  .action(async (query, options) => {
    console.log(`Searching for: "${query}" (limit: ${options.limit})`);
    console.log('\n[Not yet implemented - API integration pending]');
  });

// Decisions command
program
  .command('decisions')
  .description('List captured decisions')
  .option('-p, --project <project>', 'Filter by project')
  .option('--last <period>', 'Time period (e.g., 7d, 30d)')
  .action(async (options) => {
    console.log('Listing decisions...');
    if (options.project) console.log(`  Project: ${options.project}`);
    if (options.last) console.log(`  Period: ${options.last}`);
    console.log('\n[Not yet implemented - API integration pending]');
  });

// Assumptions command
program
  .command('assumptions')
  .description('List captured assumptions')
  .option('-p, --project <project>', 'Filter by project')
  .option('--invalid', 'Show only invalidated assumptions')
  .action(async (options) => {
    console.log('Listing assumptions...');
    if (options.project) console.log(`  Project: ${options.project}`);
    if (options.invalid) console.log('  Showing: invalidated only');
    console.log('\n[Not yet implemented - API integration pending]');
  });

// Watch command
program
  .command('watch <path>')
  .description('Watch a folder for new files')
  .option('-t, --type <type>', 'Source type (zoom, markdown)', 'markdown')
  .action(async (path, options) => {
    console.log(`Watching: ${path} (type: ${options.type})`);
    console.log('\n[Not yet implemented - file watcher pending]');
  });

// Serve command
program
  .command('serve')
  .description('Start the web UI')
  .option('-p, --port <port>', 'Port number', '3000')
  .action(async (options) => {
    console.log(`Starting web UI on port ${options.port}...`);
    console.log('\n[Not yet implemented - web UI pending]');
  });

program.parse();
