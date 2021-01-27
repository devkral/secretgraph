const path = require('path')
const { CleanWebpackPlugin } = require('clean-webpack-plugin')
const { WebpackManifestPlugin } = require('webpack-manifest-plugin')
const TsGraphQLPlugin = require('ts-graphql-plugin/webpack')

const tsgqlPlugin = new TsGraphQLPlugin({
    /* plugin options */
})

module.exports = (env, options) => ({
    context: __dirname,
    devtool: options.mode === 'development' ? 'eval' : false,
    output: {
        publicPath: '/webpack_bundles/',
        path: path.resolve(__dirname, './webpack_bundles/'),
    },
    watchOptions: {
        ignored: /node_modules/,
    },
    entry: {
        main: './assets/js/Client/index.tsx',
        'editor-cluster': './assets/js/Client/editors/cluster.tsx',
    },
    module: {
        rules: [
            {
                test: /\.(ts|js)x?$/,
                loader: 'ts-loader',
                exclude: /node_modules/,
                options: {
                    getCustomTransformers: () => ({
                        before: [
                            tsgqlPlugin.getTransformer({
                                /* transformer options */
                            }),
                        ],
                    }),
                },
            },
            {
                test: /\.css$/i,
                use: ['style-loader', 'css-loader'],
            },
        ],
    },
    resolve: {
        extensions: ['.tsx', '.jsx', '.ts', '.js', '.wasm', '.mjs', '.json'],
        fallback: {
            buffer: false,
        },
    },
    plugins: [
        // remove outdated
        new CleanWebpackPlugin(),
        new WebpackManifestPlugin(),
        tsgqlPlugin,
    ],
    optimization: {
        runtimeChunk: 'single',
        splitChunks: {
            chunks: 'all',
        },
    },
})
