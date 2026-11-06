import { remarkAdmonitions } from './compat/admonitions';
import { remarkIcons } from './compat/icons';
import { remarkGridCards } from './compat/grid-cards';
import { remarkAttrList } from './compat/attr-list';
import { remarkMermaid } from './compat/mermaid';
import { rehypeHeadingIds } from './compat/heading-ids';

export const compatRemark = [remarkAdmonitions, remarkIcons, remarkGridCards, remarkAttrList, remarkMermaid];
export const compatRehype = [rehypeHeadingIds];
