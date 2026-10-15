declare module "jest-axe" {
  export function axe(html: Element | string, options?: any): Promise<{ violations: any[] }>;
  export function toHaveNoViolations(): any;
}
