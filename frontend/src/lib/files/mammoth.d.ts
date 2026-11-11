// The standalone browser build of mammoth has the same API as the package root.
declare module 'mammoth/mammoth.browser.js' {
	import mammoth from 'mammoth';
	export default mammoth;
}
